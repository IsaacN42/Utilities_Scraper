import requests
import json
import time
from datetime import datetime, timedelta
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
USERNAME = os.getenv("HSV_USERNAME")
PASSWORD = os.getenv("HSV_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS"))
ELECTRIC_INTERVAL = os.getenv("ELECTRIC_INTERVAL", "HOURLY")
GAS_INTERVAL = os.getenv("GAS_INTERVAL", "HOURLY") 
WATER_INTERVAL = os.getenv("WATER_INTERVAL", "MONTHLY")

def convert_interval(interval):
    # convert 15_MIN to api format
    if interval == "15_MIN":
        return "FIFTEEN_MINUTE"
    return interval

BASE_URL = "https://hsvutil.smarthub.coop"

def create_session():
    # create authenticated session
    session = requests.Session()
    
    # login
    response = session.post(f"{BASE_URL}/login", data={"username": USERNAME, "password": PASSWORD}, 
                          headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        return None
    print("login successful")
    
    # get oauth token
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
    # get account and service location info
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    
    account_number = str(accounts[0]["account"])
    service_location = str(accounts[0]["serviceLocations"][0])
    print(f"detected account: {account_number}")
    print(f"detected service location: {service_location}")
    
    return account_number, service_location

def get_usage_data(session, account_number, service_location, start_date, end_date, time_frame="HOURLY"):
    # get usage data for all industries
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
    
    payload = {
        "timeFrame": time_frame,
        "userId": USERNAME,
        "screen": "USAGE_EXPLORER",
        "includeDemand": False,
        "serviceLocationNumber": service_location,
        "accountNumber": account_number,
        "industries": ["WATER", "ELECTRIC", "GAS"],
        "startDateTime": start_ms,
        "endDateTime": end_ms
    }
    
    response = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
    data = response.json()
    
    # poll until complete
    pending_shown = False
    while data.get("status") != "COMPLETE":
        if not pending_shown:
            print("data pending...")
            pending_shown = True
        time.sleep(2)
        response = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
        data = response.json()
    
    return process_usage_data(data)

def process_usage_data(data):
    # process raw usage data for industries/utilities
    processed = {}

    for industry, industry_data in data["data"].items():
        if not industry_data:
            continue
        processed[industry] = []

        for service_data in industry_data:
            # handle electric/gas meter data with series
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
                                "datetime": datetime.fromtimestamp(point.get("x",0)/1000).isoformat(),
                                "usage": point.get("y",0)
                            })

                    processed[industry].append({
                        "meterNumber": meter_number,
                        "unitOfMeasure": meter_info.get("unitOfMeasure"),
                        "flowDirection": meter_info.get("flowDirection"),
                        "isNetMeter": meter_info.get("isNetMeter", False),
                        "totalReadings": len(readings),
                        "readings": readings
                    })

            # handle water data structure
            elif industry == "WATER":
                readings = []
                unit_of_measure = service_data.get("unitOfMeasure", "GAL")
                
                # check for hourly/daily readings
                if "data" in service_data and isinstance(service_data["data"], list):
                    for point in service_data["data"]:
                        if isinstance(point, dict) and "x" in point and "y" in point:
                            readings.append({
                                "timestamp": point.get("x"),
                                "datetime": datetime.fromtimestamp(point.get("x",0)/1000).isoformat(),
                                "usage": point.get("y",0)
                            })
                
                # check for monthly format
                current = service_data.get("current")
                if current and not readings:
                    readings.append({
                        "timestamp": None,
                        "datetime": f"{current.get('month',0)}/{current.get('year',0)}",
                        "usage": current.get("usage", 0)
                    })
                    unit_of_measure = current.get("unitsOfMeasure", [unit_of_measure])[0]

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
    # save data to json file in data/utilities directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # ensure data/utilities directory exists
    data_dir = Path("data/utilities")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"hsu_usage_{timestamp}.json"
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"data saved to {filepath}")

def print_summary(data):
    # print summary of usage data
    for industry, meters in data.items():
        print(f"\n{industry}:")
        for meter in meters:
            total_usage = sum(r.get("usage", 0) for r in meter.get("readings", []))
            unit = meter.get("unitOfMeasure", "UNKNOWN")
            readings_count = meter.get("totalReadings", 0)
            print(f"  meter {meter['meterNumber']}: {readings_count} readings, {total_usage:.2f} {unit}")

def main():
    # main function
    session = create_session()
    account_number, service_location = get_account_info(session)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)
    
    all_data = {}
    
    # electric and gas with configurable intervals
    intervals = {"ELECTRIC": convert_interval(ELECTRIC_INTERVAL), "GAS": convert_interval(GAS_INTERVAL)}
    for industry in ["ELECTRIC", "GAS"]:
        data = get_usage_data(session, account_number, service_location, 
                            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), intervals[industry])
        if data and industry in data:
            all_data[industry] = data[industry]
    
    # water
    water_start = end_date - timedelta(days=31)
    water_data = get_usage_data(session, account_number, service_location, 
                              water_start.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), convert_interval(WATER_INTERVAL))
    if water_data and "WATER" in water_data:
        all_data["WATER"] = water_data["WATER"]
    
    print_summary(all_data)
    print()
    save_data(all_data)

if __name__ == "__main__":
    main()