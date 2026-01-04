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
STORE_INTERVAL = int(os.getenv("STORE_INTERVAL_MINUTES", "15"))

SESSION_FILE = "ecobee_session.json"
TOKEN_FILE = "ecobee_token.json"
DATA_FILE = "data/ecobee/ecobee_current.json"

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
                        return token
            except:
                pass
        
        context = browser.new_context()
        page = context.new_page()
        
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
        
        page.goto('https://www.ecobee.com')
        page.click('text=Sign In', timeout=10000)
        
        page.wait_for_selector('input[name="username"]', timeout=10000)
        page.fill('input[name="username"]', USERNAME)
        page.click('button[type="submit"]')
        
        page.wait_for_selector('input[name="password"]', timeout=10000)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        
        page.wait_for_selector('input[name="code"]', timeout=15000)
        
        if TOTP_SECRET:
            totp = pyotp.TOTP(TOTP_SECRET)
            code = totp.now()
            page.fill('input[name="code"]', code)
            page.click('button[type="submit"]')
        else:
            input("enter 2fa code manually, press enter when done...")
        
        page.wait_for_url('**/consumerportal/**', timeout=30000)
        context.storage_state(path=SESSION_FILE)
        
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

def get_thermostat_data(access_token, thermostat_id, start_date, end_date):
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'User-Agent': 'PythonEcobeeScraper/1.0'
    }

    payload_dict = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id
        },
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "startInterval": 0,
        "endInterval": 287,
        "columns": "zoneHvacMode,zoneCalendarEvent,zoneCoolTemp,zoneHeatTemp,zoneAveTemp,zoneHumidity,"
                   "outdoorTemp,outdoorHumidity,compCool1,compCool2,compHeat1,compHeat2,auxHeat1,auxHeat2,"
                   "auxHeat3,fan,humidifier,dehumidifier,economizer,ventilator,hvacMode,zoneClimate",
        "includeSensors": True
    }

    url = f"https://api.ecobee.com/1/runtimeReport?format=json&body={urllib.parse.quote(json.dumps(payload_dict))}"

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 500 and attempt < 2:
                time.sleep(5)
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

def load_existing_data():
    """load existing data file"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {"THERMOSTAT": []}

def get_last_timestamp(data):
    """get the most recent timestamp from existing data"""
    if not data.get("THERMOSTAT"):
        return None
    
    thermostat = data["THERMOSTAT"][0]
    if not thermostat.get("readings"):
        return None
    
    # readings are sorted chronologically
    last_reading = thermostat["readings"][-1]
    return datetime.fromisoformat(last_reading["datetime"])

def merge_data(existing, new_data):
    """merge new data into existing, removing duplicates"""
    if not new_data.get("THERMOSTAT"):
        return existing
    
    new_thermostat = new_data["THERMOSTAT"][0]
    new_readings = new_thermostat.get("readings", [])
    
    if not new_readings:
        return existing
    
    # get or create thermostat entry
    if not existing.get("THERMOSTAT"):
        existing["THERMOSTAT"] = [new_thermostat]
        return existing
    
    existing_thermostat = existing["THERMOSTAT"][0]
    existing_readings = existing_thermostat.get("readings", [])
    
    # create set of existing timestamps for deduplication
    existing_timestamps = {r["timestamp"] for r in existing_readings}
    
    # add only new readings
    added = 0
    for reading in new_readings:
        if reading["timestamp"] not in existing_timestamps:
            existing_readings.append(reading)
            added += 1
    
    # sort by timestamp
    existing_readings.sort(key=lambda x: x["timestamp"])
    
    # update counts
    existing_thermostat["readings"] = existing_readings
    existing_thermostat["totalReadings"] = len(existing_readings)
    
    return existing, added

def save_data(data):
    """save data to current file"""
    data_dir = Path(DATA_FILE).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def main():
    print("ecobee incremental scraper")
    print("="*40)
    
    # load token
    access_token = load_token()
    needs_auth = True
    
    if access_token:
        try:
            thermostat_id = get_thermostat_id(access_token)
            needs_auth = False
        except:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
    
    if needs_auth:
        print("authenticating...")
        access_token = authenticate_ecobee_browser()
        save_token(access_token)
        thermostat_id = get_thermostat_id(access_token)
    
    # load existing data
    existing_data = load_existing_data()
    last_timestamp = get_last_timestamp(existing_data)
    
    # determine fetch range
    end_date = datetime.now()
    
    if last_timestamp:
        # fetch from last timestamp + 1 day (to get overlap for dedup)
        start_date = last_timestamp - timedelta(days=1)
        print(f"fetching new data since {last_timestamp.date()}")
    else:
        # no existing data, fetch last 7 days as starting point
        start_date = end_date - timedelta(days=7)
        print("no existing data, fetching last 7 days")
    
    print(f"range: {start_date.date()} to {end_date.date()}")
    
    # fetch new data
    try:
        raw_data = get_thermostat_data(access_token, thermostat_id, start_date, end_date)
        new_data = process_data(raw_data, store_interval_minutes=STORE_INTERVAL)
        
        # merge with existing
        merged_data, added = merge_data(existing_data, new_data)
        
        # save
        save_data(merged_data)
        
        # print summary
        total = merged_data["THERMOSTAT"][0]["totalReadings"] if merged_data.get("THERMOSTAT") else 0
        print(f"added {added} new readings")
        print(f"total readings: {total}")
        
        if total > 0:
            readings = merged_data["THERMOSTAT"][0]["readings"]
            first = readings[0]["datetime"][:10]
            last = readings[-1]["datetime"][:10]
            print(f"range: {first} to {last}")
        
    except Exception as e:
        if "401" in str(e):
            print("token expired, will reauth next run")
        else:
            print(f"error: {e}")
        raise

if __name__ == "__main__":
    main()