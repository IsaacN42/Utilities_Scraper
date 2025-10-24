import requests
import json
from datetime import datetime, timedelta
import time
import os
from pathlib import Path
from dotenv import load_dotenv
import urllib.parse
try:
    from .data_availability import check_ecobee_availability
except ImportError:
    from data_availability import check_ecobee_availability

load_dotenv()
USERNAME = os.getenv("ECOBEE_USERNAME")
PASSWORD = os.getenv("ECOBEE_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS", "7"))
STORE_INTERVAL = int(os.getenv("STORE_INTERVAL_MINUTES", "15"))

CLIENT_ID = '183eORFPlXyz9BbDZwqexHPBQoVjgadh'

def authenticate_ecobee(username, password):
    auth_data = {
        'client_id': CLIENT_ID,
        'username': username,
        'password': password,
        'connection': 'Username-Password-Authentication',
        'grant_type': 'password',
        'audience': 'https://prod.ecobee.com/api/v1',
        'scope': 'openid smartWrite piiWrite piiRead smartRead deleteGrants'
    }
    response = requests.post(
        "https://auth.ecobee.com/oauth/token",
        json=auth_data,
        headers={'Content-Type': 'application/json'}
    )
    response.raise_for_status()
    token_data = response.json()
    if 'access_token' not in token_data:
        raise RuntimeError(f"Unexpected token response: {token_data}")
    print("access token obtained")
    return token_data['access_token']

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
                print(f"  500 error, retrying in {delay}s... (attempt {attempt+1})")
                time.sleep(delay)
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
    """Fetch data in chunks, working backwards from end_date"""
    all_data = {"THERMOSTAT": []}
    current_end = end_date
    chunk_num = 1
    total_chunks = ((end_date - start_date).days // chunk_size) + 1
    
    print(f"\nFetching data in {total_chunks} chunks of {chunk_size} days each...")
    
    while current_end > start_date:
        current_start = max(current_end - timedelta(days=chunk_size - 1), start_date)
        
        print(f"\n[Chunk {chunk_num}/{total_chunks}] {current_start.date()} to {current_end.date()}")
        
        try:
            raw_chunk = get_thermostat_data(access_token, thermostat_id, current_start, current_end)
            processed_chunk = process_data(raw_chunk, store_interval_minutes=store_interval_minutes)
            
            # Merge data
            for t in processed_chunk.get("THERMOSTAT", []):
                existing = next((x for x in all_data["THERMOSTAT"] if x["thermostatId"] == t["thermostatId"]), None)
                if existing:
                    # Prepend older data to beginning
                    existing["readings"] = t["readings"] + existing["readings"]
                    existing["totalReadings"] = len(existing["readings"])
                else:
                    all_data["THERMOSTAT"].append(t)
            
            readings_count = len(processed_chunk.get("THERMOSTAT", [{}])[0].get("readings", []))
            print(f"  ✓ Got {readings_count} readings")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            # Continue with next chunk on error
        
        current_end = current_start - timedelta(days=1)
        chunk_num += 1
        time.sleep(0.5)  # Small delay between chunks
    
    return all_data

def save_data(data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir = Path("data/ecobee")
    data_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ecobee_data_{timestamp}.json"
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nData saved to {filepath}")

def print_summary(data):
    print("\n" + "="*60)
    print("ECOBEE DATA SUMMARY")
    print("="*60)
    if "THERMOSTAT" in data:
        for thermostat in data["THERMOSTAT"]:
            readings_count = thermostat.get("totalReadings", 0)
            thermostat_id = thermostat.get("thermostatId", "unknown")
            print(f"Thermostat {thermostat_id}:")
            print(f"  Total readings: {readings_count}")
            
            if readings_count > 0:
                readings = thermostat.get("readings", [])
                first_date = readings[0]["datetime"][:10]
                last_date = readings[-1]["datetime"][:10]
                print(f"  Date range: {first_date} to {last_date}")
                
                # Calculate time span
                first_dt = datetime.fromisoformat(readings[0]["datetime"])
                last_dt = datetime.fromisoformat(readings[-1]["datetime"])
                days = (last_dt - first_dt).days
                print(f"  Time span: {days} days")

def main():
    print("="*60)
    print("ECOBEE DATA SCRAPER")
    print("="*60)
    
    access_token = authenticate_ecobee(USERNAME, PASSWORD)
    thermostat_id = get_thermostat_id(access_token)
    print(f"Using thermostat: {thermostat_id}\n")

    # Check data availability
    availability = check_ecobee_availability(access_token, thermostat_id)
    max_chunk_size = availability['max_days_per_request']
    
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
        print(f"   From: {start_date.date()}")
        print(f"   To: {end_date.date()}")
    
    # Fetch data
    days_to_fetch = (end_date - start_date).days
    
    if days_to_fetch <= max_chunk_size:
        # Single request
        print(f"\nSingle request (within {max_chunk_size} day limit)")
        raw_data = get_thermostat_data(access_token, thermostat_id, start_date, end_date)
        processed_data = process_data(raw_data, store_interval_minutes=STORE_INTERVAL)
    else:
        # Multiple chunks
        processed_data = fetch_data_in_chunks(
            access_token, thermostat_id, start_date, end_date,
            max_chunk_size, STORE_INTERVAL
        )
    
    print_summary(processed_data)
    save_data(processed_data)
    print("\n✓ Ecobee data collection complete")

if __name__ == "__main__":
    main()
