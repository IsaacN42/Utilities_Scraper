import requests
import json
import time
from datetime import datetime, timedelta
import os
from pathlib import Path
from dotenv import load_dotenv
from .data_availability import check_hsv_availability

load_dotenv()
USERNAME = os.getenv("HSV_USERNAME")
PASSWORD = os.getenv("HSV_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS"))
ELECTRIC_INTERVAL = os.getenv("ELECTRIC_INTERVAL", "HOURLY")
GAS_INTERVAL = os.getenv("GAS_INTERVAL", "HOURLY") 
WATER_INTERVAL = os.getenv("WATER_INTERVAL", "HOURLY")

def convert_interval(interval):
    if interval == "15_MIN":
        return "FIFTEEN_MINUTE"
    return interval

BASE_URL = "https://hsvutil.smarthub.coop"

def create_session():
    session = requests.Session()
    
    response = session.post(f"{BASE_URL}/login", data={"username": USERNAME, "password": PASSWORD}, 
                          headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        return None
    print("login successful")
    
    response = session.post(f"{BASE_URL}/services/oauth/auth/v2", 
                          data=f"userId={USERNAME}&password={PASSWORD}",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code != 200:
        return None
    
    token = response.json().get("authorizationToken")
    if not token:
        return None
    
    session.headers.update({'Authorization': f'Bearer {token}'})
    print("oauth token obtained")
    return session

def get_account_info(session):
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    
    account_number = str(accounts[0]["account"])
    service_location = str(accounts[0]["serviceLocations"][0])
    print(f"detected account: {account_number}")
    print(f"detected service location: {service_location}")
    
    return account_number, service_location

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
    
    pending_shown = False
    retries = 30
    while data.get("status") != "COMPLETE" and retries > 0:
        if not pending_shown:
            print("  waiting for data...")
            pending_shown = True
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir = Path("data/utilities")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"hsu_usage_{timestamp}.json"
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nData saved to {filepath}")

def print_summary(data):
    print("\n" + "="*60)
    print("HSV UTILITIES DATA SUMMARY")
    print("="*60)
    for industry, meters in data.items():
        print(f"\n{industry}:")
        if not meters:
            print("  No data")
            continue
        for meter in meters:
            total_usage = sum(r.get("usage", 0) for r in meter.get("readings", []))
            unit = meter.get("unitOfMeasure", "UNKNOWN")
            readings_count = meter.get("totalReadings", 0)
            print(f"  Meter {meter['meterNumber']}: {readings_count} readings, {total_usage:.2f} {unit}")
            
            if readings_count > 0 and meter["readings"][0].get("datetime"):
                first = meter["readings"][0]["datetime"]
                last = meter["readings"][-1]["datetime"]
                if isinstance(first, str) and len(first) > 10:
                    print(f"    Date range: {first[:10]} to {last[:10]}")

def main():
    print("="*60)
    print("HSV UTILITIES DATA SCRAPER")
    print("="*60)
    
    session = create_session()
    account_number, service_location = get_account_info(session)
    
    # Check data availability
    print()
    availability = check_hsv_availability(session, account_number, service_location)
    
    # Determine date range
    if DATA_PERIOD_DAYS < 0:
        # Fetch all available historical data
        print(f"\n📅 Fetching ALL available historical data")
        start_date = availability['data_start_date']
        end_date = datetime.now()
        print(f"   From: {start_date.date()}")
        print(f"   To: {end_date.date()}")
        print(f"   Total days: {availability['total_days_available']}")
    else:
        # Fetch specified number of days
        print(f"\n📅 Fetching last {DATA_PERIOD_DAYS} days")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)
        # Don't go before data start date
        if start_date < availability['data_start_date']:
            print(f"   ⚠ Requested {DATA_PERIOD_DAYS} days, but only {availability['total_days_available']} available")
            start_date = availability['data_start_date']
        print(f"   From: {start_date.date()}")
        print(f"   To: {end_date.date()}")
    
    all_data = {}
    
    # Configure intervals for each utility
    intervals = {
        "ELECTRIC": convert_interval(ELECTRIC_INTERVAL), 
        "GAS": convert_interval(GAS_INTERVAL),
        "WATER": convert_interval(WATER_INTERVAL)
    }
    
    # HSV can handle large requests (up to 360 days)
    # So we can request all utilities together if within limits
    days_to_fetch = (end_date - start_date).days
    max_chunk_size = availability['max_days_per_request']
    
    if days_to_fetch <= max_chunk_size:
        # Single request for each utility
        print(f"\nFetching all utilities (within {max_chunk_size} day limit)...")
        for industry, interval in intervals.items():
            print(f"\n{industry} ({interval}):")
            data = get_usage_data(
                session, account_number, service_location,
                start_date, end_date, interval, industries=[industry]
            )
            if data and industry in data:
                all_data[industry] = data[industry]
                print(f"  ✓ Retrieved {len(data[industry])} meters")
    else:
        # Need to chunk requests
        print(f"\nFetching in chunks (need {days_to_fetch} days, max is {max_chunk_size})...")
        
        for industry, interval in intervals.items():
            print(f"\n{industry} ({interval}):")
            industry_data = []
            
            current_end = end_date
            chunk_num = 1
            total_chunks = (days_to_fetch // max_chunk_size) + 1
            
            while current_end > start_date:
                current_start = max(current_end - timedelta(days=max_chunk_size - 1), start_date)
                
                print(f"  [Chunk {chunk_num}/{total_chunks}] {current_start.date()} to {current_end.date()}")
                
                chunk_data = get_usage_data(
                    session, account_number, service_location,
                    current_start, current_end, interval, industries=[industry]
                )
                
                if chunk_data and industry in chunk_data:
                    # Merge readings for each meter
                    for meter in chunk_data[industry]:
                        existing_meter = next(
                            (m for m in industry_data if m["meterNumber"] == meter["meterNumber"]), 
                            None
                        )
                        if existing_meter:
                            # Prepend older readings
                            existing_meter["readings"] = meter["readings"] + existing_meter["readings"]
                            existing_meter["totalReadings"] = len(existing_meter["readings"])
                        else:
                            industry_data.append(meter)
                
                current_end = current_start - timedelta(days=1)
                chunk_num += 1
                time.sleep(1)
            
            if industry_data:
                all_data[industry] = industry_data
                print(f"  ✓ Total: {len(industry_data)} meters")
    
    print_summary(all_data)
    save_data(all_data)
    print("\n✓ HSV data collection complete")

if __name__ == "__main__":
    main()
