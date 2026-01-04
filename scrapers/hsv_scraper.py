import requests
import json
import time
from datetime import datetime, timedelta
import os
from pathlib import Path
from dotenv import load_dotenv
import urllib.parse

load_dotenv()
USERNAME = os.getenv("HSV_USERNAME")
PASSWORD = os.getenv("HSV_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS", "7"))
ELECTRIC_INTERVAL = os.getenv("ELECTRIC_INTERVAL", "HOURLY")
GAS_INTERVAL = os.getenv("GAS_INTERVAL", "HOURLY") 
WATER_INTERVAL = os.getenv("WATER_INTERVAL", "MONTHLY")

BASE_URL = "https://hsvutil.smarthub.coop"
TOKEN_FILE = "hsv_token.json"

def convert_interval(interval):
    if interval == "15_MIN":
        return "FIFTEEN_MINUTE"
    return interval

def save_token(token_data):
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'token': token_data['authorizationToken'],
            'expiration': token_data['expiration'],
            'timestamp': datetime.now().isoformat()
        }, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            data = json.load(f)
            exp = datetime.fromtimestamp(data['expiration'] / 1000)
            if exp > datetime.now():
                return data['token']
    return None

def create_session():
    session = requests.Session()
    
    # try existing token
    token = load_token()
    if token:
        session.headers.update({'Authorization': f'Bearer {token}'})
        try:
            response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
            if response.status_code == 200:
                print("using cached token")
                return session
        except:
            pass
    
    # fresh login
    response = session.post(f"{BASE_URL}/login", data={"username": USERNAME, "password": PASSWORD}, 
                          headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
    
    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        return None
    
    response = session.post(f"{BASE_URL}/services/oauth/auth/v2", 
                          data=f"userId={urllib.parse.quote(USERNAME)}&password={urllib.parse.quote(PASSWORD)}",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    if response.status_code != 200:
        return None
    
    token_data = response.json()
    token = token_data.get("authorizationToken")
    if not token:
        return None
    
    save_token(token_data)
    session.headers.update({'Authorization': f'Bearer {token}'})
    print("login successful")
    return session

def get_account_info(session):
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    
    account_number = str(accounts[0]["account"])
    service_location = str(accounts[0]["serviceLocations"][0])
    print(f"account: {account_number}, service location: {service_location}")
    
    return account_number, service_location

def check_data_availability(session, account_number, service_location):
    print("\nchecking data availability...")
    
    end_date = datetime.now()
    test_periods = [30, 90, 180, 365, 540]
    earliest_with_data = None
    
    for days in test_periods:
        test_start = end_date - timedelta(days=days)
        test_end = min(test_start + timedelta(days=30), end_date)
        
        try:
            data = get_usage_data(session, account_number, service_location,
                                test_start, test_end, "DAILY", ["ELECTRIC"])
            
            if data and "ELECTRIC" in data and data["ELECTRIC"]:
                meter = data["ELECTRIC"][0]
                if meter.get("totalReadings", 0) > 5:
                    earliest_with_data = test_start
                    print(f"  data found at {test_start.date()} ({days} days)")
        except:
            pass
        
        time.sleep(0.3)
    
    if earliest_with_data:
        days_available = (end_date - earliest_with_data).days
        print(f"earliest data: {earliest_with_data.date()}")
        print(f"total days available: {days_available}")
        return earliest_with_data, days_available
    
    print("no historical data found, defaulting to 30 days")
    return end_date - timedelta(days=30), 30

def get_usage_data(session, account_number, service_location, start_date, end_date, time_frame="HOURLY", industries=None):
    if industries is None:
        industries = ["WATER", "ELECTRIC", "GAS"]
    
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
    
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)
    
    payload = {
        "timeFrame": time_frame,
        "userId": USERNAME,
        "screen": "USAGE_EXPLORER",
        "includeDemand": False,
        "serviceLocationNumber": service_location,
        "accountNumber": account_number,
        "industries": industries,
        "startDateTime": start_ms,
        "endDateTime": end_ms
    }
    
    response = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
    data = response.json()
    
    retries = 30
    while data.get("status") != "COMPLETE" and retries > 0:
        time.sleep(2)
        response = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
        data = response.json()
        retries -= 1
    
    return process_usage_data(data)

def process_usage_data(data):
    processed = {}

    for industry, industry_data in data["data"].items():
        if not industry_data:
            continue
        
        processed[industry] = []

        for service_data in industry_data:
            meters_info = service_data.get("meters", [])
            series_data = service_data.get("series", [])

            if meters_info and series_data:
                for meter_info in meters_info:
                    meter_number = meter_info.get("meterNumber")
                    meter_series = next((s for s in series_data if s.get("name") == meter_number), None)

                    readings = []
                    if meter_series and meter_series.get("data"):
                        for point in meter_series["data"]:
                            readings.append({
                                "timestamp": point.get("x"),
                                "datetime": datetime.fromtimestamp(point.get("x", 0) / 1000).isoformat(),
                                "usage": point.get("y", 0)
                            })

                    processed[industry].append({
                        "meterNumber": meter_number,
                        "unitOfMeasure": meter_info.get("unitOfMeasure"),
                        "flowDirection": meter_info.get("flowDirection"),
                        "isNetMeter": meter_info.get("isNetMeter", False),
                        "totalReadings": len(readings),
                        "readings": readings
                    })

            elif industry == "WATER":
                readings = []
                unit_of_measure = service_data.get("unitOfMeasure", "GAL")
                
                if "data" in service_data and isinstance(service_data["data"], list):
                    for point in service_data["data"]:
                        if isinstance(point, dict) and "x" in point and "y" in point:
                            readings.append({
                                "timestamp": point.get("x"),
                                "datetime": datetime.fromtimestamp(point.get("x", 0) / 1000).isoformat(),
                                "usage": point.get("y", 0)
                            })
                
                current = service_data.get("current")
                if current and not readings:
                    readings.append({
                        "timestamp": None,
                        "datetime": f"{current.get('month', 0)}/{current.get('year', 0)}",
                        "usage": current.get("usage", 0)
                    })
                    unit_of_measure = current.get("unitsOfMeasure", [unit_of_measure])[0]

                if readings:
                    processed[industry].append({
                        "meterNumber": service_data.get("serviceLocationNumber", "UNKNOWN"),
                        "unitOfMeasure": unit_of_measure,
                        "flowDirection": "DELIVERED",
                        "isNetMeter": False,
                        "totalReadings": len(readings),
                        "readings": readings
                    })

    return processed

def save_data(data):
    data_dir = Path("data/utilities")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # save as current file for incremental updates
    current_file = data_dir / "hsv_current.json"
    with open(current_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    # also save timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = data_dir / f"hsu_usage_{timestamp}.json"
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\ndata saved to {current_file}")
    print(f"backup saved to {backup_file}")

def print_summary(data):
    print("\n" + "="*60)
    print("hsv utilities data summary")
    print("="*60)
    for industry, meters in data.items():
        print(f"\n{industry}:")
        if not meters:
            print("  no data")
            continue
        for meter in meters:
            total_usage = sum(r.get("usage", 0) for r in meter.get("readings", []))
            unit = meter.get("unitOfMeasure", "UNKNOWN")
            readings_count = meter.get("totalReadings", 0)
            print(f"  meter {meter['meterNumber']}: {readings_count} readings, {total_usage:.2f} {unit}")
            
            if readings_count > 0 and meter["readings"][0].get("datetime"):
                first = meter["readings"][0]["datetime"]
                last = meter["readings"][-1]["datetime"]
                if isinstance(first, str) and len(first) > 10:
                    print(f"    date range: {first[:10]} to {last[:10]}")

def main():
    print("="*60)
    print("hsv utilities data scraper")
    print("="*60)
    
    session = create_session()
    if not session:
        print("\nauthentication failed")
        return
    
    account_number, service_location = get_account_info(session)
    
    # date range
    end_date = datetime.now()
    
    if DATA_PERIOD_DAYS < 0:
        actual_start, days_available = check_data_availability(session, account_number, service_location)
        start_date = actual_start
        print(f"\nfetching all available data ({days_available} days)")
    else:
        print(f"\nfetching last {DATA_PERIOD_DAYS} days")
        start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)
    
    print(f"from: {start_date.date()}")
    print(f"to: {end_date.date()}")
    
    all_data = {}
    
    # configure intervals
    intervals = {
        "ELECTRIC": convert_interval(ELECTRIC_INTERVAL), 
        "GAS": convert_interval(GAS_INTERVAL),
        "WATER": convert_interval(WATER_INTERVAL)
    }
    
    days_to_fetch = (end_date - start_date).days
    max_chunk_size = 360
    
    if days_to_fetch <= max_chunk_size:
        print(f"\nfetching utilities...")
        for industry, interval in intervals.items():
            print(f"  {industry} ({interval})", end="", flush=True)
            data = get_usage_data(
                session, account_number, service_location,
                start_date, end_date, interval, industries=[industry]
            )
            if data and industry in data:
                all_data[industry] = data[industry]
                total_readings = sum(m.get("totalReadings", 0) for m in data[industry])
                print(f" - {total_readings} readings")
    else:
        print(f"\nfetching in chunks...")
        total_chunks = (days_to_fetch // max_chunk_size) + 1
        
        for industry, interval in intervals.items():
            print(f"\n{industry} ({interval}):")
            industry_data = []
            
            current_end = end_date
            chunk_num = 1
            
            while current_end > start_date:
                current_start = max(current_end - timedelta(days=max_chunk_size - 1), start_date)
                
                print(f"  chunk {chunk_num}/{total_chunks}: {current_start.date()} to {current_end.date()}", end="", flush=True)
                
                chunk_data = get_usage_data(
                    session, account_number, service_location,
                    current_start, current_end, interval, industries=[industry]
                )
                
                if chunk_data and industry in chunk_data:
                    for meter in chunk_data[industry]:
                        existing_meter = next(
                            (m for m in industry_data if m["meterNumber"] == meter["meterNumber"]), 
                            None
                        )
                        if existing_meter:
                            existing_meter["readings"] = meter["readings"] + existing_meter["readings"]
                            existing_meter["totalReadings"] = len(existing_meter["readings"])
                        else:
                            industry_data.append(meter)
                    
                    readings_count = sum(m.get("totalReadings", 0) for m in chunk_data[industry])
                    print(f" - {readings_count} readings")
                
                current_end = current_start - timedelta(days=1)
                chunk_num += 1
                time.sleep(0.5)
            
            if industry_data:
                all_data[industry] = industry_data
    
    print_summary(all_data)
    save_data(all_data)
    print("\ncollection complete")

if __name__ == "__main__":
    main()