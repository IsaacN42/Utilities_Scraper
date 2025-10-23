"""ecobee scraper for home assistant integration."""
import aiohttp
import json
from datetime import datetime, timedelta
import logging

_LOGGER = logging.getLogger(__name__)


async def test_ecobee_connection(username: str, password: str) -> bool:
    """test ecobee connection with provided credentials."""
    try:
        auth_data = {
            'client_id': '183eORFPlXyz9BbDZwqexHPBQoVjgadh',
            'username': username,
            'password': password,
            'connection': 'Username-Password-Authentication',
            'grant_type': 'password',
            'audience': 'https://prod.ecobee.com/api/v1',
            'scope': 'openid smartWrite piiWrite piiRead smartRead deleteGrants'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://auth.ecobee.com/oauth/token",
                json=auth_data,
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return False
                
                token_data = await response.json()
                return 'access_token' in token_data
                
    except Exception as e:
        _LOGGER.error(f"ecobee connection test failed: {e}")
        return False


class EcobeeScraper:
    """async ecobee scraper for ha integration."""
    
    def __init__(self, username, password, data_period_days=7):
        self.username = username
        self.password = password
        self.data_period_days = data_period_days
        self.access_token = None
        
    async def authenticate(self):
        """get access token."""
        auth_data = {
            'client_id': '183eORFPlXyz9BbDZwqexHPBQoVjgadh',
            'username': self.username,
            'password': self.password,
            'connection': 'Username-Password-Authentication',
            'grant_type': 'password',
            'audience': 'https://prod.ecobee.com/api/v1',
            'scope': 'openid smartWrite piiWrite piiRead smartRead deleteGrants'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://auth.ecobee.com/oauth/token",
                json=auth_data,
                headers={'Content-Type': 'application/json'}
            ) as response:
                response.raise_for_status()
                token_data = await response.json()
                if 'access_token' not in token_data:
                    raise RuntimeError(f"unexpected token response: {token_data}")
                self.access_token = token_data['access_token']
                _LOGGER.info("ecobee access token obtained")
                return self.access_token
    
    async def get_thermostat_id(self):
        """get default thermostat id."""
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.ecobee.com/1/user",
                params={"format": "json", "json": "{}"},
                headers=headers
            ) as response:
                response.raise_for_status()
                user_data = await response.json()
                return user_data['user']['defaultThermostatIdentifier']
    
    async def get_thermostat_data(self, thermostat_id, start_date, end_date):
        """fetch thermostat runtime data."""
        import urllib.parse
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'User-Agent': 'HAEcobeeScraper/1.0'
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
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json()
    
    def process_data(self, data):
        """process raw ecobee data."""
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
    
    async def save_data(self, data, data_dir):
        """save data to json file."""
        from pathlib import Path
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"ecobee_data_{timestamp}.json"
        filepath = data_path / filename
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        _LOGGER.info(f"ecobee data saved to {filepath}")
    
    async def async_get_data(self, data_dir=None):
        """main async data collection method."""
        try:
            # authenticate
            await self.authenticate()
            
            # get thermostat
            thermostat_id = await self.get_thermostat_id()
            _LOGGER.info(f"using thermostat: {thermostat_id}")
            
            # calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.data_period_days)
            
            # fetch data
            raw_data = await self.get_thermostat_data(thermostat_id, start_date, end_date)
            
            # process
            processed_data = self.process_data(raw_data)
            
            # save if data_dir provided
            if data_dir:
                await self.save_data(processed_data, data_dir)
            
            _LOGGER.info(f"collected ecobee data: {len(processed_data.get('THERMOSTAT', []))} thermostats")
            return processed_data
            
        except Exception as e:
            _LOGGER.error(f"failed to collect ecobee data: {e}")
            raise


async def collect_ecobee_data(
    username: str,
    password: str,
    data_period_days: int,
    data_dir: str
) -> bool:
    """main function to collect ecobee data."""
    try:
        scraper = EcobeeScraper(username, password, data_period_days)
        await scraper.async_get_data(data_dir)
        return True
    except Exception as e:
        _LOGGER.error(f"ecobee data collection failed: {e}")
        return False