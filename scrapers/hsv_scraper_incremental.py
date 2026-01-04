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
ELECTRIC_INTERVAL = os.getenv("ELECTRIC_INTERVAL", "HOURLY")
GAS_INTERVAL = os.getenv("GAS_INTERVAL", "HOURLY") 
WATER_INTERVAL = os.getenv("WATER_INTERVAL", "MONTHLY")

BASE_URL = "https://hsvutil.smarthub.coop"
TOKEN_FILE = "hsv_token.json"
DATA_FILE = "data/utilities/hsv_current.json"

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
    
    token = load_token()
    if token:
        session.headers.update({'Authorization': f'Bearer {token}'})
        try:
            response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
            if response.status_code == 200:
                return session
        except:
            pass
    
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
    return session

def get_account_info(session):
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    
    account_number = str(accounts[0]["account"])
    service_location = str(accounts[0]["serviceLocations"][0])
    
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

def load_existing_data():
    """load existing data file"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def get_last_timestamp(data, industry):
    """get most recent timestamp for an industry"""
    if industry not in data or not data[industry]:
        return None
    
    meter = data[industry][0]
    if not meter.get("readings"):
        return None
    
    last_reading = meter["readings"][-1]
    if not last_reading.get("datetime"):
        return None
    
    # handle different datetime formats
    dt_str = last_reading["datetime"]
    if "/" in dt_str:  # monthly water format
        return None
    
    return datetime.fromisoformat(dt_str)

def merge_data(existing, new_data, industry):
    """merge new data for specific industry, removing duplicates"""
    if industry not in new_data or not new_data[industry]:
        return existing, 0
    
    new_meter = new_data[industry][0]
    new_readings = new_meter.get("readings", [])
    
    if not new_readings:
        return existing, 0
    
    # get or create industry entry
    if industry not in existing:
        existing[industry] = [new_meter]
        return existing, len(new_readings)
    
    existing_meter = existing[industry][0]
    existing_readings = existing_meter.get("readings", [])
    
    # create set of existing timestamps
    existing_timestamps = {r.get("timestamp") for r in existing_readings if r.get("timestamp")}
    
    # add only new readings
    added = 0
    for reading in new_readings:
        if reading.get("timestamp") and reading["timestamp"] not in existing_timestamps:
            existing_readings.append(reading)
            added += 1
    
    # sort by timestamp
    existing_readings.sort(key=lambda x: x.get("timestamp", 0))
    
    # update counts
    existing_meter["readings"] = existing_readings
    existing_meter["totalReadings"] = len(existing_readings)
    
    return existing, added

def save_data(data):
    """save data to current file"""
    data_dir = Path(DATA_FILE).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def main():
    print("hsv incremental scraper")
    print("="*40)
    
    session = create_session()
    if not session:
        print("authentication failed")
        return
    
    account_number, service_location = get_account_info(session)
    
    # load existing data
    existing_data = load_existing_data()
    
    intervals = {
        "ELECTRIC": convert_interval(ELECTRIC_INTERVAL), 
        "GAS": convert_interval(GAS_INTERVAL),
        "WATER": convert_interval(WATER_INTERVAL)
    }
    
    total_added = 0
    
    for industry, interval in intervals.items():
        last_timestamp = get_last_timestamp(existing_data, industry)
        
        end_date = datetime.now()
        
        if last_timestamp:
            # fetch from last timestamp - 1 day (for overlap/dedup)
            start_date = last_timestamp - timedelta(days=1)
            print(f"{industry}: fetching since {last_timestamp.date()}")
        else:
            # no existing data, fetch last 7 days
            start_date = end_date - timedelta(days=7)
            print(f"{industry}: no existing data, fetching last 7 days")
        
        # fetch new data
        new_data = get_usage_data(
            session, account_number, service_location,
            start_date, end_date, interval, industries=[industry]
        )
        
        # merge
        existing_data, added = merge_data(existing_data, new_data, industry)
        total_added += added
        
        if industry in existing_data and existing_data[industry]:
            meter = existing_data[industry][0]
            total = meter.get("totalReadings", 0)
            print(f"  added {added} new readings (total: {total})")
    
    # save
    save_data(existing_data)
    
    print(f"\ntotal new readings: {total_added}")

if __name__ == "__main__":
    main()