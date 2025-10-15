import requests
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()
USERNAME = os.getenv("ECOBEE_USERNAME")
PASSWORD = os.getenv("ECOBEE_PASSWORD")
DATA_PERIOD_DAYS = int(os.getenv("DATA_PERIOD_DAYS", "7"))

def authenticate_ecobee(username, password):
    auth_data = {
        'client_id': '183eORFPlXyz9BbDZwqexHPBQoVjgadh',
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

def get_thermostat_data(access_token, thermostat_id, start_date, end_date):
    import urllib.parse

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
        "columns": "zoneHvacMode,zoneCalendarEvent,zoneCoolTemp,zoneHeatTemp,zoneAveTemp,zoneHumidity,outdoorTemp,outdoorHumidity,compCool1,compCool2,compHeat1,compHeat2,auxHeat1,auxHeat2,auxHeat3,fan,humidifier,dehumidifier,economizer,ventilator,hvacMode,zoneClimate",
        "includeSensors": True
    }

    payload_str = json.dumps(payload_dict)
    url = f"https://api.ecobee.com/1/runtimeReport?format=json&body={urllib.parse.quote(payload_str)}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def process_data(data):
    if not data or 'reportList' not in data:
        return {}

    processed = {"THERMOSTAT": []}

    for report in data['reportList']:
        thermostat_id = report['thermostatIdentifier']
        columns = data['columns'].split(',')

        readings = []
        for row in report['rowList']:
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
    filename = f"ecobee_data_{timestamp}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"data saved to {filename}")

def print_summary(data):
    if "THERMOSTAT" in data:
        for thermostat in data["THERMOSTAT"]:
            readings_count = thermostat.get("totalReadings", 0)
            thermostat_id = thermostat.get("thermostatId", "unknown")
            print(f"thermostat {thermostat_id}: {readings_count} readings")

def main():
    access_token = get_access_token()
    thermostat_id = get_thermostat_id(access_token)
    print(f"using thermostat: {thermostat_id}")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DATA_PERIOD_DAYS)

    raw_data = get_thermostat_data(access_token, thermostat_id, start_date, end_date)
    processed_data = process_data(raw_data)
    print_summary(processed_data)
    save_data(processed_data)
    print("ecobee data collection complete")

if __name__ == "__main__":
    main()