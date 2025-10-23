"""HSV Utilities scraper for Home Assistant integration."""
import asyncio
import aiofiles
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://hsvutil.smarthub.coop"


async def test_hsv_connection(username: str, password: str) -> bool:
    """test hsv connection with provided credentials."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/login",
                data={"username": username, "password": password},
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True
            ) as response:
                if not ("/ui/" in str(response.url) or "dashboard" in str(response.url).lower()):
                    return False
                
            async with session.post(
                f"{BASE_URL}/services/oauth/auth/v2",
                data=f"userId={username}&password={password}",
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            ) as response:
                if response.status != 200:
                    return False
                
                data = await response.json()
                return "authorizationToken" in data
                
    except Exception as e:
        _LOGGER.error("hsv connection test failed: %s", e)
        return False


async def create_session(username: str, password: str) -> Optional[aiohttp.ClientSession]:
    """create authenticated session."""
    session = aiohttp.ClientSession()
    
    try:
        async with session.post(
            f"{BASE_URL}/login",
            data={"username": username, "password": password},
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True
        ) as response:
            if not ("/ui/" in str(response.url) or "dashboard" in str(response.url).lower()):
                await session.close()
                return None
            _LOGGER.debug("hsv login successful")
        
        async with session.post(
            f"{BASE_URL}/services/oauth/auth/v2",
            data=f"userId={username}&password={password}",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        ) as response:
            if response.status != 200:
                await session.close()
                return None
            
            data = await response.json()
            token = data.get("authorizationToken")
            if not token:
                await session.close()
                return None
            
            session.headers.update({'Authorization': f'Bearer {token}'})
            _LOGGER.debug("hsv oauth token obtained")
            return session
            
    except Exception as e:
        _LOGGER.error("failed to create hsv session: %s", e)
        await session.close()
        return None


async def get_account_info(session: aiohttp.ClientSession) -> Optional[dict]:
    """get account and service location info."""
    try:
        async with session.get(f"{BASE_URL}/services/secured/accounts") as response:
            if response.status != 200:
                _LOGGER.error(f"failed to get accounts: status {response.status}")
                return None
            
            accounts = await response.json()
            if not accounts:
                _LOGGER.error("no accounts found")
                return None
            
            account_number = str(accounts[0]["account"])
            
            async with session.get(
                f"{BASE_URL}/services/secured/accounts/{account_number}/service-locations"
            ) as response:
                if response.status != 200:
                    _LOGGER.error(f"failed to get service locations: status {response.status}")
                    return None
                
                service_locations = await response.json()
                return {
                    "account_number": account_number,
                    "service_locations": service_locations
                }
                
    except Exception as e:
        _LOGGER.error("failed to get account info: %s", e)
        return None


async def collect_usage_data(
    session: aiohttp.ClientSession,
    account_info: dict,
    data_period_days: int,
    intervals: dict
) -> Optional[dict]:
    """collect usage data for all utilities."""
    try:
        end_date = datetime.now()
        if data_period_days == -1:
            start_date = end_date - timedelta(days=730)
        else:
            start_date = end_date - timedelta(days=data_period_days)
        
        _LOGGER.debug(f"fetching hsv data from {start_date.date()} to {end_date.date()}")
        
        payload = {
            "accountNumber": account_info["account_number"],
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "serviceLocationIds": [loc["id"] for loc in account_info["service_locations"]],
            "interval": "HOURLY"
        }
        
        async with session.post(
            f"{BASE_URL}/services/secured/utility-usage/poll",
            json=payload
        ) as response:
            if response.status != 200:
                _LOGGER.error(f"failed to poll usage data: status {response.status}")
                return None
            
            data = await response.json()
            
            # poll until complete
            max_retries = 30
            retry_count = 0
            while data.get("status") == "IN_PROGRESS" and retry_count < max_retries:
                await asyncio.sleep(2)
                retry_count += 1
                async with session.post(
                    f"{BASE_URL}/services/secured/utility-usage/poll",
                    json=payload
                ) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
            
            if data.get("status") == "IN_PROGRESS":
                _LOGGER.error("polling timeout after 30 retries")
                return None
            
            return process_usage_data(data)
            
    except Exception as e:
        _LOGGER.error("failed to collect usage data: %s", e)
        return None


def process_usage_data(data: dict) -> dict:
    """process raw usage data into structured format."""
    processed = {}
    
    for service_location in data.get("serviceLocations", []):
        for meter in service_location.get("meters", []):
            utility_type = meter.get("utilityType", "UNKNOWN")
            meter_number = meter.get("meterNumber", "unknown")
            unit = meter.get("unitOfMeasure", "unknown")
            
            readings = []
            for reading in meter.get("readings", []):
                readings.append({
                    "timestamp": reading.get("timestamp"),
                    "usage": reading.get("usage", 0),
                    "datetime": datetime.fromtimestamp(reading.get("timestamp", 0) / 1000).isoformat()
                })
            
            if utility_type not in processed:
                processed[utility_type] = []
            
            processed[utility_type].append({
                "meterNumber": meter_number,
                "unitOfMeasure": unit,
                "flowDirection": meter.get("flowDirection", "DELIVERED"),
                "readings": readings
            })
    
    return processed


async def save_data(data: dict, data_dir: str) -> None:
    """save data to json file in specified directory."""
    try:
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hsu_usage_{timestamp}.json"
        filepath = data_path / filename
        
        async with aiofiles.open(filepath, "w") as f:
            await f.write(json.dumps(data, indent=2))
        
        _LOGGER.info("hsv data saved to %s", filepath)
        
    except Exception as e:
        _LOGGER.error("failed to save hsv data: %s", e)


async def collect_hsv_data(
    username: str,
    password: str,
    data_period_days: int,
    data_dir: str,
    intervals: Optional[dict] = None
) -> bool:
    """main function to collect hsv data."""
    if intervals is None:
        intervals = {
            "ELECTRIC": "HOURLY",
            "GAS": "HOURLY",
            "WATER": "MONTHLY"
        }
    
    try:
        session = await create_session(username, password)
        if not session:
            _LOGGER.error("failed to create hsv session")
            return False
        
        try:
            account_info = await get_account_info(session)
            if not account_info:
                _LOGGER.error("failed to get hsv account info")
                return False
            
            data = await collect_usage_data(session, account_info, data_period_days, intervals)
            if not data:
                _LOGGER.error("failed to collect hsv usage data")
                return False
            
            await save_data(data, data_dir)
            return True
            
        finally:
            await session.close()
            
    except Exception as e:
        _LOGGER.error("hsv data collection failed: %s", e)
        return False