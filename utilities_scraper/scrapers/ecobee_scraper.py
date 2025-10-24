import requests
import json
from datetime import datetime, timedelta
import time
import os
from pathlib import Path
from dotenv import load_dotenv
import urllib.parse

load_dotenv()
USERNAME = os.getenv("ECOBEE_USERNAME")
PASSWORD = os.getenv("ECOBEE_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS", "7"))
STORE_INTERVAL = int(os.getenv("STORE_INTERVAL_MINUTES", "15"))  # 5, 10, 15, etc.

CLIENT_ID = '183eORFPlXyz9BbDZwqexHPBQoVjgadh'
CHUNK_DAYS = 33  # Max days per request allowed by Ecobee API

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

def get_access_token():
    return authenticate_ecobee(USERNAME, PASSWORD)

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
        "endInterval": 287,  # 5-min intervals in a day
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
                print(f"500 Internal Server Error, retrying in {delay}s... (attempt {attempt+1})")
                time.sleep(delay)
            else:
                raise

def process_data(data, store_interval_minutes=15):
    if not data or 'reportList' not in data:
        return {}

    skip = store_interval_minutes // 5  # downsample to requested interval
    columns = data['columns'].split(',')
    processed = {"THERMOSTAT": []}

    for report in data['reportList']:
        thermostat_id = report['thermostatIdentifier']
        readings = []

        for idx, row in enumerate(report['rowList']):
            if idx % skip != 0:
                continue  # skip to downsample

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

def save_data(data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir = Path("data/ecobee")
    data_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ecobee_data_{timestamp}.json"
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"data saved to {filepath}")

def print_summary(data):
    if "THERMOSTAT" in data:
        for thermostat in data["THERMOSTAT"]:
            readings_count = thermostat.get("totalReadings", 0)
            thermostat_id = thermostat.get("thermostatId", "unknown")
            print(f"thermostat {thermostat_id}: {readings_count} readings")

def fetch_ecobee_all_time(access_token, thermostat_id, store_interval_minutes=15):
    all_data = {"THERMOSTAT": []}
    current_end = datetime.now()

    while True:
        current_start = current_end - timedelta(days=CHUNK_DAYS - 1)
        if current_start.year < 2009:
            current_start = datetime(2009, 1, 1)

        print(f"Fetching data from {current_start.date()} to {current_end.date()}")
        raw_chunk = get_thermostat_data(access_token, thermostat_id, current_start, current_end)
        processed_chunk = process_data(raw_chunk, store_interval_minutes=store_interval_minutes)

        if all(len(t.get("readings", [])) == 0 for t in processed_chunk.get("THERMOSTAT", [])):
            print("No more data found, stopping.")
            break

        for t in processed_chunk.get("THERMOSTAT", []):
            existing = next((x for x in all_data["THERMOSTAT"] if x["thermostatId"] == t["thermostatId"]), None)
            if existing:
                existing["readings"].extend(t["readings"])
                existing["totalReadings"] = len(existing["readings"])
            else:
                all_data["THERMOSTAT"].append(t)

        if current_start <= datetime(2009, 1, 1):
            break
        current_end = current_start - timedelta(days=1)

    return all_data

def main():
    access_token = get_access_token()
    thermostat_id = get_thermostat_id(access_token)
    print(f"using thermostat: {thermostat_id}")

    if DATA_PERIOD_DAYS < 0:
        processed_data = fetch_ecobee_all_time(access_token, thermostat_id, store_interval_minutes=STORE_INTERVAL)
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)
        raw_data = get_thermostat_data(access_token, thermostat_id, start_date, end_date)
        processed_data = process_data(raw_data, store_interval_minutes=STORE_INTERVAL)

    print_summary(processed_data)
    save_data(processed_data)
    print("ecobee data collection complete")

if __name__ == "__main__":
    main()
