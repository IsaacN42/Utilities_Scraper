import requests
import json
import time
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

# === CONFIG ===
HSV_USERNAME = os.getenv("HSV_USERNAME")
HSV_PASSWORD = os.getenv("HSV_PASSWORD")
ECOBEE_USERNAME = os.getenv("ECOBEE_USERNAME")
ECOBEE_PASSWORD = os.getenv("ECOBEE_PASSWORD")
ECOBEE_CLIENT_ID = '183eORFPlXyz9BbDZwqexHPBQoVjgadh'

BASE_URL = "https://hsvutil.smarthub.coop"

# ======== HSV FUNCTIONS ========
def create_hsv_session():
    session = requests.Session()
    resp = session.post(f"{BASE_URL}/login",
                        data={"username": HSV_USERNAME, "password": HSV_PASSWORD},
                        headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
    if not ("/ui/" in resp.url or "dashboard" in resp.url.lower()):
        raise RuntimeError("HSV login failed")
    print("HSV login successful")
    
    resp = session.post(f"{BASE_URL}/services/oauth/auth/v2",
                        data=f"userId={HSV_USERNAME}&password={HSV_PASSWORD}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    token = resp.json().get("authorizationToken")
    if not token:
        raise RuntimeError("HSV oauth token failed")
    session.headers.update({'Authorization': f'Bearer {token}'})
    print("HSV oauth token obtained")
    return session

def get_hsv_account_info(session):
    resp = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": HSV_USERNAME})
    accounts = resp.json()
    account_number = str(accounts[0]["account"])
    service_location = str(accounts[0]["serviceLocations"][0])
    print(f"HSV account: {account_number}, service location: {service_location}")
    return account_number, service_location

def get_hsv_usage(session, account_number, service_location, start_date, end_date):
    if isinstance(start_date, datetime):
        start_date = start_date.strftime("%Y-%m-%d")
    if isinstance(end_date, datetime):
        end_date = end_date.strftime("%Y-%m-%d")
    
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
    
    payload = {
        "timeFrame": "HOURLY",
        "userId": HSV_USERNAME,
        "screen": "USAGE_EXPLORER",
        "includeDemand": False,
        "serviceLocationNumber": service_location,
        "accountNumber": account_number,
        "industries": ["ELECTRIC"],
        "startDateTime": start_ms,
        "endDateTime": end_ms
    }
    
    resp = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
    data = resp.json()
    
    while data.get("status") != "COMPLETE":
        time.sleep(2)
        resp = session.post(f"{BASE_URL}/services/secured/utility-usage/poll", json=payload)
        data = resp.json()
    
    # Count total readings
    total = 0
    for industry_data in data["data"].get("ELECTRIC", []):
        for meter_info in industry_data.get("meters", []):
            meter_number = meter_info.get("meterNumber")
            series_data = industry_data.get("series", [])
            meter_series = next((s for s in series_data if s.get("name") == meter_number), None)
            if meter_series and meter_series.get("data"):
                total += len(meter_series["data"])
    return total

# ======== ECOBEE FUNCTIONS ========
def authenticate_ecobee(username, password):
    auth_data = {
        'client_id': ECOBEE_CLIENT_ID,
        'username': username,
        'password': password,
        'connection': 'Username-Password-Authentication',
        'grant_type': 'password',
        'audience': 'https://prod.ecobee.com/api/v1',
        'scope': 'openid smartWrite piiWrite piiRead smartRead deleteGrants'
    }
    resp = requests.post("https://auth.ecobee.com/oauth/token",
                         json=auth_data, headers={'Content-Type':'application/json'})
    resp.raise_for_status()
    token_data = resp.json()
    if 'access_token' not in token_data:
        raise RuntimeError(f"Unexpected token response: {token_data}")
    print("Ecobee access token obtained")
    return token_data['access_token']

def get_ecobee_thermostat_id(access_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get("https://api.ecobee.com/1/user", params={"format":"json","json":"{}"}, headers=headers)
    resp.raise_for_status()
    user_data = resp.json()
    return user_data['user']['defaultThermostatIdentifier']

def get_ecobee_data(access_token, thermostat_id, start_date, end_date):
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
        "columns": "zoneAveTemp",
        "includeSensors": True
    }
    url = f"https://api.ecobee.com/1/runtimeReport?format=json&body={urllib.parse.quote(json.dumps(payload_dict))}"
    
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # Count rows
            total = 0
            for report in data.get('reportList', []):
                total += len(report.get('rowList', []))
            return total
        except requests.HTTPError as e:
            if e.response.status_code == 500 and attempt < 2:
                print(f"500 error, retrying {attempt+1}/3...")
                time.sleep(5)
            else:
                raise

# ======== TESTING FUNCTIONS ========
def test_max_window(name, test_func, max_known_days=None):
    """Test maximum request window size"""
    print(f"\n{'='*60}")
    print(f"{name} - MAXIMUM REQUEST WINDOW TEST")
    print(f"{'='*60}")
    
    days = 30
    step = 30
    last_success = 30
    
    print(f"Testing {days} days (baseline)...", end=" ", flush=True)
    try:
        result = test_func(days)
        print(f"✓ Success ({result} data points)")
        last_success = days
    except Exception as e:
        print(f"✗ Failed: {e}")
        return last_success
    
    # Test larger windows up to max_known_days or 365
    max_test = min(max_known_days or 365, 365)
    days += step
    while days <= max_test:
        print(f"Testing {days} days...", end=" ", flush=True)
        try:
            result = test_func(days)
            print(f"✓ Success ({result} data points)")
            last_success = days
            days += step
        except Exception as e:
            print(f"✗ Failed: {e}")
            break
    
    print(f"\n📊 Maximum window: {last_success} days")
    return last_success

def find_data_start(name, test_func_single_day, max_window_days, min_valid_points=10):
    """Find when historical data starts using binary search with exact boundary detection"""
    print(f"\n{'='*60}")
    print(f"{name} - HISTORICAL DATA START DATE")
    print(f"{'='*60}")
    
    now = datetime.now()
    
    # First, do a quick linear scan every 10 days to find approximate range
    print(f"Phase 1: Quick scan every 10 days to find approximate range...")
    print(f"(Points < {min_valid_points} are considered empty/invalid)\n")
    
    days_back = 10
    last_valid_day = None
    
    while days_back <= 365:
        target_date = now - timedelta(days=days_back)
        try:
            count = test_func_single_day(target_date)
            
            if count >= min_valid_points:
                print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): {count} points ✓")
                last_valid_day = days_back
            else:
                print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): {count} points (too few)")
                # Found the approximate boundary, now search backwards from last_valid_day
                break
                
        except Exception as e:
            error_msg = str(e)[:80]
            print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): Error - {error_msg}")
            # Error might indicate boundary, search backwards from last_valid_day
            break
        
        days_back += 10
    
    if last_valid_day is None:
        print("\n⚠ No valid data found in recent history")
        return None, 0
    
    # Now count up day-by-day from last_valid_day to find exact boundary
    print(f"\nPhase 2: Counting up from day {last_valid_day} to find exact boundary...")
    
    days_back = last_valid_day + 1
    consecutive_invalid = 0
    exact_boundary = last_valid_day
    
    while consecutive_invalid < 3 and days_back <= 365:
        target_date = now - timedelta(days=days_back)
        
        try:
            count = test_func_single_day(target_date)
            
            if count >= min_valid_points:
                print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): {count} points ✓")
                exact_boundary = days_back
                consecutive_invalid = 0
            else:
                print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): {count} points (empty)")
                consecutive_invalid += 1
                
        except Exception as e:
            error_msg = str(e)[:60]
            print(f"Day {days_back} ({target_date.strftime('%Y-%m-%d')}): Error - {error_msg}")
            consecutive_invalid += 1
        
        days_back += 1
    
    data_start_date = now - timedelta(days=exact_boundary)
    
    print(f"\n✓ Found exact boundary after {consecutive_invalid} consecutive invalid days")
    print(f"\n📅 Data starts: {data_start_date.strftime('%Y-%m-%d')}")
    print(f"   Total history: {exact_boundary} days (~{exact_boundary/30:.1f} months)")
    
    return data_start_date, exact_boundary

# ======== MAIN ========
def main():
    results = {}
    
    # HSV Testing
    print("\n" + "="*60)
    print("HSV UTILITIES DATA AVAILABILITY CHECK")
    print("="*60)
    
    hsv_session = create_hsv_session()
    account, service_location = get_hsv_account_info(hsv_session)
    
    # Test cumulative ranges for max window
    def hsv_test_cumulative(days):
        end = datetime.now()
        start = end - timedelta(days=days)
        return get_hsv_usage(hsv_session, account, service_location, start, end)
    
    # Test single day for finding data start
    def hsv_test_single_day(target_date):
        # Request just this one day
        start = target_date
        end = target_date + timedelta(days=1)
        return get_hsv_usage(hsv_session, account, service_location, start, end)
    
    hsv_max = test_max_window("HSV UTILITIES", hsv_test_cumulative)
    # For HSV, 192 points per day is normal (8 readings/hour * 24 hours), so use 50 as minimum
    hsv_start_date, hsv_total_days = find_data_start("HSV UTILITIES", hsv_test_single_day, hsv_max, min_valid_points=50)
    
    results['hsv'] = {
        'max_days_per_request': hsv_max,
        'data_start_date': hsv_start_date.strftime('%Y-%m-%d') if hsv_start_date else 'Unknown',
        'total_days_available': hsv_total_days
    }
    
    # Ecobee Testing
    print("\n" + "="*60)
    print("ECOBEE DATA AVAILABILITY CHECK")
    print("="*60)
    
    access_token = authenticate_ecobee(ECOBEE_USERNAME, ECOBEE_PASSWORD)
    thermostat_id = get_ecobee_thermostat_id(access_token)
    print(f"Using thermostat: {thermostat_id}")
    
    # Test cumulative ranges for max window
    def ecobee_test_cumulative(days):
        end = datetime.now()
        start = end - timedelta(days=days)
        return get_ecobee_data(access_token, thermostat_id, start, end)
    
    # Test single day for finding data start
    def ecobee_test_single_day(target_date):
        # Request just this one day
        start = target_date
        end = target_date
        return get_ecobee_data(access_token, thermostat_id, start, end)
    
    eco_max = test_max_window("ECOBEE", ecobee_test_cumulative)
    # For Ecobee, 288 points per day is normal (288 5-min intervals), so use 100 as minimum
    eco_start_date, eco_total_days = find_data_start("ECOBEE", ecobee_test_single_day, eco_max, min_valid_points=100)
    
    results['ecobee'] = {
        'max_days_per_request': eco_max,
        'data_start_date': eco_start_date.strftime('%Y-%m-%d') if eco_start_date else 'Unknown',
        'total_days_available': eco_total_days
    }
    
    # Save results to text file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"data_availability_{timestamp}.txt"
    
    with open(filename, 'w') as f:
        f.write("DATA AVAILABILITY REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("HSV UTILITIES:\n")
        f.write(f"    Max days per request: {results['hsv']['max_days_per_request']} days\n")
        f.write(f"    Data starts: {results['hsv']['data_start_date']}\n")
        f.write(f"    Total history available: {results['hsv']['total_days_available']} days (~{results['hsv']['total_days_available']/30:.1f} months)\n\n")
        
        f.write("ECOBEE:\n")
        f.write(f"    Max days per request: {results['ecobee']['max_days_per_request']} days\n")
        f.write(f"    Data starts: {results['ecobee']['data_start_date']}\n")
        f.write(f"    Total history available: {results['ecobee']['total_days_available']} days (~{results['ecobee']['total_days_available']/30:.1f} months)\n")
    
    print(f"\n{'='*60}")
    print(f"RESULTS SAVED TO: {filename}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()