import requests
import json
from datetime import datetime, timedelta
import time
import os
from pathlib import Path
from dotenv import load_dotenv
import urllib.parse
import pyotp
from playwright.sync_api import sync_playwright

load_dotenv()

USERNAME = os.getenv("ECOBEE_USERNAME")
PASSWORD = os.getenv("ECOBEE_PASSWORD")
TOTP_SECRET = os.getenv("ECOBEE_TOTP_SECRET")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS", "7"))
STORE_INTERVAL = int(os.getenv("STORE_INTERVAL_MINUTES", "15"))

SESSION_FILE = "ecobee_session.json"
TOKEN_FILE = "ecobee_token.json"

def save_token(token):
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'access_token': token,
            'timestamp': datetime.now().isoformat()
        }, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            data = json.load(f)
            return data.get('access_token')
    return None

def authenticate_ecobee_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        # try reuse session
        if os.path.exists(SESSION_FILE):
            try:
                context = browser.new_context(storage_state=SESSION_FILE)
                page = context.new_page()
                page.goto('https://www.ecobee.com/consumerportal/index.html', timeout=15000)
                
                if 'consumerportal' in page.url:
                    token = page.evaluate("""
                        () => localStorage.getItem('access_token') || 
                             sessionStorage.getItem('access_token')
                    """)
                    if token:
                        browser.close()
                        print("using cached session")
                        return token
            except:
                pass
        
        # fresh login
        print("logging in via browser...")
        context = browser.new_context()
        page = context.new_page()
        
        # intercept token
        token_holder = {'token': None}
        
        def handle_response(response):
            if 'authCallback' in response.url:
                try:
                    body = response.request.post_data
                    if body and 'access_token=' in body:
                        token_holder['token'] = body.split('access_token=')[1].split('&')[0]
                except:
                    pass
        
        page.on('response', handle_response)
        
        # login flow
        page.goto('https://www.ecobee.com')
        page.click('text=Sign In', timeout=10000)
        
        page.wait_for_selector('input[name="username"]', timeout=10000)
        page.fill('input[name="username"]', USERNAME)
        page.click('button[type="submit"]')
        
        page.wait_for_selector('input[name="password"]', timeout=10000)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        
        # 2fa
        page.wait_for_selector('input[name="code"]', timeout=15000)
        
        if TOTP_SECRET:
            totp = pyotp.TOTP(TOTP_SECRET)
            code = totp.now()
            page.fill('input[name="code"]', code)
            page.click('button[type="submit"]')
        else:
            input("enter 2fa code manually, press enter when done...")
        
        page.wait_for_url('**/consumerportal/**', timeout=30000)
        
        # save session
        context.storage_state(path=SESSION_FILE)
        
        # get token
        token = token_holder['token']
        
        if not token:
            token = page.evaluate("""
                () => localStorage.getItem('access_token') || 
                     sessionStorage.getItem('access_token')
            """)
        
        if not token:
            cookies = context.cookies()
            for cookie in cookies:
                if 'token' in cookie['name'].lower():
                    token = cookie['value']
                    break
        
        browser.close()
        
        if not token:
            raise RuntimeError("could not extract access token")
        
        print("login successful")
        return token

def get_thermostat_id(access_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(
        "https://api.ecobee.com/1/user",
        params={"format": "json", "json": "{}"},
        headers=headers
    )
    response.raise_for_status()
    user_data = response.json()
    return user_data['user']['defaultThermostatIdentifier']

def check_data_availability(access_token, thermostat_id):
    print("\nchecking data availability...")
    
    end_date = datetime.now()
    test_periods = [30, 90, 180, 365, 540, 730]
    earliest_with_data = None
    
    for days in test_periods:
        test_start = end_date - timedelta(days=days)
        test_end = min(test_start + timedelta(days=30), end_date)
        
        try:
            data = get_thermostat_data(access_token, thermostat_id, test_start, test_end, retries=1, delay=0)
            
            if data and 'reportList' in data and data['reportList']:
                report = data['reportList'][0]
                if 'rowList' in report and len(report['rowList']) > 10:
                    earliest_with_data = test_start
                    print(f"  data found at {test_start.date()} ({days} days)")
        except:
            pass
        
        time.sleep(0.3)
    
    if earliest_with_data:
        month_start = earliest_with_data
        month_end = min(month_start + timedelta(days=31), end_date)
        
        try:
            data = get_thermostat_data(access_token, thermostat_id, month_start, month_end, retries=1, delay=0)
            if data and 'reportList' in data and data['reportList']:
                report = data['reportList'][0]
                if 'rowList' in report and len(report['rowList']) > 0:
                    first_row = report['rowList'][0]
                    parts = first_row if isinstance(first_row, list) else first_row.split(',')
                    if len(parts) >= 2:
                        actual_start = datetime.strptime(parts[0], "%Y-%m-%d")
                        days_available = (end_date - actual_start).days
                        print(f"earliest data: {actual_start.date()}")
                        print(f"total days available: {days_available}")
                        return actual_start, days_available
        except:
            pass
        
        days_available = (end_date - earliest_with_data).days
        print(f"earliest data: ~{earliest_with_data.date()}")
        print(f"total days available: ~{days_available}")
        return earliest_with_data, days_available
    
    print("no historical data found, defaulting to 30 days")
    return end_date - timedelta(days=30), 30

def get_thermostat_data(access_token, thermostat_id, start_date, end_date, retries=3, delay=5):
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'User-Agent': 'PythonEcobeeScraper/1.0'
    }

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    payload_dict = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id
        },
        "startDate": start_date_str,
        "endDate": end_date_str,
        "startInterval": 0,
        "endInterval": 287,
        "columns": "zoneHvacMode,zoneCalendarEvent,zoneCoolTemp,zoneHeatTemp,zoneAveTemp,zoneHumidity,"
                   "outdoorTemp,outdoorHumidity,compCool1,compCool2,compHeat1,compHeat2,auxHeat1,auxHeat2,"
                   "auxHeat3,fan,humidifier,dehumidifier,economizer,ventilator,hvacMode,zoneClimate",
        "includeSensors": True
    }

    payload_str = json.dumps(payload_dict)
    url = f"https://api.ecobee.com/1/runtimeReport?format=json&body={urllib.parse.quote(payload_str)}"

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 500 and attempt < retries - 1:
                time.sleep(delay)
            elif e.response.status_code == 401:
                raise
            else:
                raise

def process_data(data, store_interval_minutes=15):
    if not data or 'reportList' not in data:
        return {}

    skip = store_interval_minutes // 5
    columns = data['columns'].split(',')
    processed = {"THERMOSTAT": []}

    for report in data['reportList']:
        thermostat_id = report['thermostatIdentifier']
        readings = []

        for idx, row in enumerate(report['rowList']):
            if idx % skip != 0:
                continue

            parts = row if isinstance(row, list) else row.split(',')
            if len(parts) < 2:
                continue

            dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S")
            reading = {
                "timestamp": int(dt.timestamp() * 1000),
                "datetime": dt.isoformat(),
                "data": {}
            }

            for i, column in enumerate(columns):
                if i + 2 < len(parts):
                    reading["data"][column] = parts[i + 2]

            readings.append(reading)

        processed["THERMOSTAT"].append({
            "thermostatId": thermostat_id,
            "totalReadings": len(readings),
            "readings": readings
        })

    return processed

def fetch_data_in_chunks(access_token, thermostat_id, start_date, end_date, chunk_size, store_interval_minutes):
    all_data = {"THERMOSTAT": []}
    current_end = end_date
    chunk_num = 1
    total_chunks = ((end_date - start_date).days // chunk_size) + 1
    
    print(f"\nfetching data in {total_chunks} chunks...")
    
    while current_end > start_date:
        current_start = max(current_end - timedelta(days=chunk_size - 1), start_date)
        
        print(f"  chunk {chunk_num}/{total_chunks}: {current_start.date()} to {current_end.date()}", end="", flush=True)
        
        try:
            raw_chunk = get_thermostat_data(access_token, thermostat_id, current_start, current_end)
            processed_chunk = process_data(raw_chunk, store_interval_minutes=store_interval_minutes)
            
            for t in processed_chunk.get("THERMOSTAT", []):
                existing = next((x for x in all_data["THERMOSTAT"] if x["thermostatId"] == t["thermostatId"]), None)
                if existing:
                    existing["readings"] = t["readings"] + existing["readings"]
                    existing["totalReadings"] = len(existing["readings"])
                else:
                    all_data["THERMOSTAT"].append(t)
            
            readings_count = len(processed_chunk.get("THERMOSTAT", [{}])[0].get("readings", []))
            print(f" - {readings_count} readings")
            
        except Exception as e:
            print(f" - error: {e}")
            if "401" in str(e):
                raise
        
        current_end = current_start - timedelta(days=1)
        chunk_num += 1
        time.sleep(0.5)
    
    return all_data

def save_data(data):
    """save data to json file"""
    data_dir = Path("data/ecobee")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # save as current file for incremental updates
    current_file = data_dir / "ecobee_current.json"
    with open(current_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    # also save timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = data_dir / f"ecobee_data_{timestamp}.json"
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\ndata saved to {current_file}")
    print(f"backup saved to {backup_file}")

def print_summary(data):
    print("\n" + "="*60)
    print("ecobee data summary")
    print("="*60)
    if "THERMOSTAT" in data:
        for thermostat in data["THERMOSTAT"]:
            readings_count = thermostat.get("totalReadings", 0)
            thermostat_id = thermostat.get("thermostatId", "unknown")
            print(f"thermostat {thermostat_id}:")
            print(f"  total readings: {readings_count}")
            
            if readings_count > 0:
                readings = thermostat.get("readings", [])
                first_date = readings[0]["datetime"][:10]
                last_date = readings[-1]["datetime"][:10]
                print(f"  date range: {first_date} to {last_date}")
                
                first_dt = datetime.fromisoformat(readings[0]["datetime"])
                last_dt = datetime.fromisoformat(readings[-1]["datetime"])
                days = (last_dt - first_dt).days
                print(f"  time span: {days} days")

def main():
    print("="*60)
    print("ecobee data scraper")
    print("="*60)
    
    # try load existing token
    access_token = load_token()
    needs_auth = True
    
    if access_token:
        try:
            thermostat_id = get_thermostat_id(access_token)
            print(f"using cached token")
            print(f"thermostat: {thermostat_id}")
            needs_auth = False
        except:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
    
    if needs_auth:
        access_token = authenticate_ecobee_browser()
        save_token(access_token)
        thermostat_id = get_thermostat_id(access_token)
        print(f"thermostat: {thermostat_id}")

    # date range
    end_date = datetime.now()
    
    if DATA_PERIOD_DAYS < 0:
        actual_start, days_available = check_data_availability(access_token, thermostat_id)
        start_date = actual_start
        print(f"\nfetching all available data ({days_available} days)")
    else:
        print(f"\nfetching last {DATA_PERIOD_DAYS} days")
        start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)
    
    print(f"from: {start_date.date()}")
    print(f"to: {end_date.date()}")
    
    # fetch data
    days_to_fetch = (end_date - start_date).days
    max_chunk_size = 31
    
    try:
        if days_to_fetch <= max_chunk_size:
            print(f"\nfetching data...")
            raw_data = get_thermostat_data(access_token, thermostat_id, start_date, end_date)
            processed_data = process_data(raw_data, store_interval_minutes=STORE_INTERVAL)
        else:
            processed_data = fetch_data_in_chunks(
                access_token, thermostat_id, start_date, end_date,
                max_chunk_size, STORE_INTERVAL
            )
        
        print_summary(processed_data)
        save_data(processed_data)
        print("\ncollection complete")
        
    except Exception as e:
        if "401" in str(e):
            print("\ntoken expired, please run again")
        raise

if __name__ == "__main__":
    main()