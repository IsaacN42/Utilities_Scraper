"""
Data Availability Library
Determines available historical data for HSV and Ecobee APIs
"""
import sys
from pathlib import Path

# Add parent directory to path for imports when run as module
if __package__:
    # Running as part of package
    pass
else:
    # Running standalone
    sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import json
import time
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

class DataAvailability:
    """Cache for data availability information"""
    _cache = {}
    
    @classmethod
    def get_cached(cls, key):
        """Get cached availability info (valid for 24 hours)"""
        if key in cls._cache:
            data, timestamp = cls._cache[key]
            if datetime.now() - timestamp < timedelta(hours=24):
                return data
        return None
    
    @classmethod
    def set_cached(cls, key, data):
        """Cache availability info"""
        cls._cache[key] = (data, datetime.now())

# ======== HSV AVAILABILITY ========
def check_hsv_availability(session=None, account_number=None, service_location=None):
    """
    Check HSV data availability
    Returns: {
        'max_days_per_request': int,
        'data_start_date': datetime,
        'total_days_available': int
    }
    """
    cache_key = f"hsv_{account_number}"
    cached = DataAvailability.get_cached(cache_key)
    if cached:
        print(f"Using cached HSV availability (data starts: {cached['data_start_date'].date()})")
        return cached
    
    print("Checking HSV data availability...")
    
    # Test max window size
    max_days = test_hsv_max_window(session, account_number, service_location)
    
    # Find data start date
    start_date, total_days = find_hsv_data_start(session, account_number, service_location)
    
    result = {
        'max_days_per_request': max_days,
        'data_start_date': start_date,
        'total_days_available': total_days
    }
    
    DataAvailability.set_cached(cache_key, result)
    print(f"✓ HSV: {total_days} days available (from {start_date.date()}), max {max_days} days/request")
    return result

def test_hsv_max_window(session, account_number, service_location):
    """Test maximum request window for HSV"""
    def test_func(days):
        end = datetime.now()
        start = end - timedelta(days=days)
        return get_hsv_usage_count(session, account_number, service_location, start, end)
    
    # Quick test: 30, 90, 180, 360
    for days in [30, 90, 180, 360]:
        try:
            test_func(days)
        except:
            return days - 90  # Back off to previous successful
    return 360

def find_hsv_data_start(session, account_number, service_location):
    """Find when HSV data starts"""
    now = datetime.now()
    
    # Quick scan every 30 days
    days_back = 30
    last_valid = 30
    
    while days_back <= 365:
        target_date = now - timedelta(days=days_back)
        try:
            count = get_hsv_usage_count(
                session, account_number, service_location,
                target_date, target_date + timedelta(days=1)
            )
            if count >= 50:  # Valid data threshold
                last_valid = days_back
            else:
                break
        except:
            break
        days_back += 30
    
    # Fine-tune with single day checks
    for day in range(last_valid + 1, min(last_valid + 30, 365)):
        target_date = now - timedelta(days=day)
        try:
            count = get_hsv_usage_count(
                session, account_number, service_location,
                target_date, target_date + timedelta(days=1)
            )
            if count >= 50:
                last_valid = day
            else:
                break
        except:
            break
    
    return now - timedelta(days=last_valid), last_valid

def get_hsv_usage_count(session, account_number, service_location, start_date, end_date):
    """Get HSV usage data point count (lightweight check)"""
    BASE_URL = "https://hsvutil.smarthub.coop"
    USERNAME = os.getenv("HSV_USERNAME")
    
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)
    
    payload = {
        "timeFrame": "HOURLY",
        "userId": USERNAME,
        "screen": "USAGE_EXPLORER",
        "includeDemand": False,
        "serviceLocationNumber": service_location,
        "accountNumber": account_number,
        "industries": ["ELECTRIC"],  # Just check electric for speed
        "startDateTime": start_ms,
        "endDateTime": end_ms
    }
    
    resp = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
    data = resp.json()
    
    retries = 10
    while data.get("status") != "COMPLETE" and retries > 0:
        time.sleep(1)
        resp = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
        data = resp.json()
        retries -= 1
    
    total = 0
    for industry_data in data["data"].get("ELECTRIC", []):
        for meter_info in industry_data.get("meters", []):
            meter_number = meter_info.get("meterNumber")
            series_data = industry_data.get("series", [])
            meter_series = next((s for s in series_data if s.get("name") == meter_number), None)
            if meter_series and meter_series.get("data"):
                total += len(meter_series["data"])
    return total

# ======== ECOBEE AVAILABILITY ========
def check_ecobee_availability(access_token=None, thermostat_id=None):
    """
    Check Ecobee data availability
    Returns: {
        'max_days_per_request': int,
        'data_start_date': datetime,
        'total_days_available': int
    }
    """
    cache_key = f"ecobee_{thermostat_id}"
    cached = DataAvailability.get_cached(cache_key)
    if cached:
        print(f"Using cached Ecobee availability (data starts: {cached['data_start_date'].date()})")
        return cached
    
    print("Checking Ecobee data availability...")
    
    # We know from testing: max is 30 days
    max_days = 30
    
    # Find data start date
    start_date, total_days = find_ecobee_data_start(access_token, thermostat_id)
    
    result = {
        'max_days_per_request': max_days,
        'data_start_date': start_date,
        'total_days_available': total_days
    }
    
    DataAvailability.set_cached(cache_key, result)
    print(f"✓ Ecobee: {total_days} days available (from {start_date.date()}), max {max_days} days/request")
    return result

def find_ecobee_data_start(access_token, thermostat_id):
    """Find when Ecobee data starts"""
    now = datetime.now()
    
    # Quick scan every 30 days
    days_back = 30
    last_valid = 30
    
    while days_back <= 365:
        target_date = now - timedelta(days=days_back)
        try:
            count = get_ecobee_usage_count(access_token, thermostat_id, target_date, target_date)
            if count >= 100:  # Valid data threshold (288 points per day normally)
                last_valid = days_back
            else:
                break
        except:
            break
        days_back += 30
    
    # Fine-tune with single day checks
    for day in range(last_valid + 1, min(last_valid + 30, 365)):
        target_date = now - timedelta(days=day)
        try:
            count = get_ecobee_usage_count(access_token, thermostat_id, target_date, target_date)
            if count >= 100:
                last_valid = day
            else:
                break
        except:
            break
    
    return now - timedelta(days=last_valid), last_valid

def get_ecobee_usage_count(access_token, thermostat_id, start_date, end_date):
    """Get Ecobee usage data point count (lightweight check)"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'User-Agent': 'PythonEcobeeScraper/1.0'
    }
    
    payload_dict = {
        "selection": {"selectionType": "thermostats", "selectionMatch": thermostat_id},
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "startInterval": 0,
        "endInterval": 287,
        "columns": "zoneAveTemp",  # Just one column for speed
        "includeSensors": False
    }
    url = f"https://api.ecobee.com/1/runtimeReport?format=json&body={urllib.parse.quote(json.dumps(payload_dict))}"
    
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            total = 0
            for report in data.get('reportList', []):
                total += len(report.get('rowList', []))
            return total
        except requests.HTTPError as e:
            if e.response.status_code == 500 and attempt < 1:
                time.sleep(2)
            else:
                raise
    return 0
