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
        # Step 1: Login
        async with session.post(
            f"{BASE_URL}/login",
            data={"username": username, "password": password},
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            final_url = str(response.url)
            
            if not ("/ui/" in final_url or "dashboard" in final_url.lower()):
                _LOGGER.error(f"Login failed - redirected to: {final_url}")
                await session.close()
                return None
            _LOGGER.debug("hsv login successful")
        
        # Step 2: Get OAuth token
        async with session.post(
            f"{BASE_URL}/services/oauth/auth/v2",
            data=f"userId={username}&password={password}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                _LOGGER.error(f"OAuth failed: status {response.status}, {error_text}")
                await session.close()
                return None
            
            data = await response.json()
            token = data.get("authorizationToken")
            
            if not token:
                _LOGGER.error(f"No token in OAuth response: {data}")
                await session.close()
                return None
            
            session.headers.update({'Authorization': f'Bearer {token}'})
            _LOGGER.debug("hsv oauth token obtained")
            return session
            
    except Exception as e:
        _LOGGER.error("failed to create hsv session: %s", e)
        await session.close()
        return None


async def get_account_info(session: aiohttp.ClientSession, username: str) -> Optional[dict]:
    """get account and service location info."""
    try:
        async with session.get(
            f"{BASE_URL}/services/secured/accounts",
            params={"user": username}
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                _LOGGER.error(f"failed to get accounts: status {response.status}, response: {error_text}")
                return None
            
            accounts = await response.json()
            if not accounts:
                _LOGGER.error("no accounts found")
                return None
            
            account = accounts[0]
            account_number = str(account["account"])
            
            # Service locations are IN the account response
            service_locations = account.get("serviceLocations", [])
            if not service_locations:
                _LOGGER.error("no service locations found")
                return None
            
            # Convert to expected format
            formatted_locations = [{"id": str(loc)} for loc in service_locations]
            
            _LOGGER.debug(f"detected account: {account_number}, service locations: {formatted_locations}")
            
            return {
                "account_number": account_number,
                "service_locations": formatted_locations
            }
                
    except Exception as e:
        _LOGGER.error("failed to get account info: %s", e)
        return None


async def collect_usage_data(
    session: aiohttp.ClientSession,
    account_info: dict,
    username: str,
    data_period_days: int,
    intervals: dict
) -> Optional[dict]:
    """collect usage data for all utilities."""
    try:
        end_date = datetime.now()
        if data_period_days == -1:
            start_date = end_date - timedelta(days=90)
        else:
            start_date = end_date - timedelta(days=data_period_days)
        
        # Convert to milliseconds like CLI version
        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)
        
        _LOGGER.debug(f"fetching hsv data from {start_date.date()} to {end_date.date()}")
        
        # Get first service location as string (not array)
        service_location = str(account_info["service_locations"][0]["id"])
        
        # Use CLI payload structure
        payload = {
            "timeFrame": "HOURLY",
            "userId": username,
            "screen": "USAGE_EXPLORER",
            "includeDemand": False,
            "serviceLocationNumber": service_location,
            "accountNumber": account_info["account_number"],
            "industries": ["WATER", "ELECTRIC", "GAS"],
            "startDateTime": start_ms,
            "endDateTime": end_ms
        }
        
        async with session.post(
            f"{BASE_URL}/services/secured/utility-usage/poll",
            json=payload
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                _LOGGER.error(f"failed to poll usage data: status {response.status}, response: {error_text}")
                return None
            
            data = await response.json()
            
            # Poll until complete
            max_retries = 30
            retry_count = 0
            pending_shown = False
            
            while data.get("status") != "COMPLETE" and retry_count < max_retries:
                if not pending_shown:
                    _LOGGER.info("HSV data pending...")
                    pending_shown = True
                    
                await asyncio.sleep(2)
                retry_count += 1
                
                async with session.post(
                    f"{BASE_URL}/services/secured/utility-usage/poll",
                    json=payload
                ) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
            
            if data.get("status") != "COMPLETE":
                _LOGGER.error("polling timeout after 30 retries")
                return None
            
            return process_usage_data(data)
            
    except Exception as e:
        _LOGGER.error("failed to collect usage data: %s", e)
        return None


def process_usage_data(data: dict) -> dict:
    """process raw usage data from CLI-style response."""
    processed = {}
    
    # CLI returns data in "data" key with industry names
    for industry, industry_data in data.get("data", {}).items():
        if not industry_data:
            continue
            
        processed[industry] = []
        
        for service_data in industry_data:
            # Handle electric/gas with meters and series
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
                                "usage": point.get("y", 0),
                                "datetime": datetime.fromtimestamp(point.get("x", 0) / 1000).isoformat()
                            })
                    
                    processed[industry].append({
                        "meterNumber": meter_number,
                        "unitOfMeasure": meter_info.get("unitOfMeasure"),
                        "flowDirection": meter_info.get("flowDirection"),
                        "readings": readings
                    })
            
            # Handle water data
            elif industry == "WATER":
                readings = []
                unit_of_measure = service_data.get("unitOfMeasure", "GAL")
                
                if "data" in service_data and isinstance(service_data["data"], list):
                    for point in service_data["data"]:
                        if isinstance(point, dict) and "x" in point and "y" in point:
                            readings.append({
                                "timestamp": point.get("x"),
                                "usage": point.get("y", 0),
                                "datetime": datetime.fromtimestamp(point.get("x", 0) / 1000).isoformat()
                            })
                
                # Monthly format
                current = service_data.get("current")
                if current and not readings:
                    readings.append({
                        "timestamp": None,
                        "datetime": f"{current.get('month', 0)}/{current.get('year', 0)}",
                        "usage": current.get("usage", 0)
                    })
                    unit_of_measure = current.get("unitsOfMeasure", [unit_of_measure])[0]
                
                processed[industry].append({
                    "meterNumber": service_data.get("serviceLocationNumber", "UNKNOWN"),
                    "unitOfMeasure": unit_of_measure,
                    "flowDirection": "DELIVERED",
                    "readings": readings
                })
    
    return processed


async def save_data(data: dict, data_dir: str) -> None:
    """save data to json file - single file, append new readings."""
    try:
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        
        # use single filename
        filepath = data_path / "hsv_usage_historical.json"
        
        # load existing data if it exists
        existing_data = {}
        if filepath.exists():
            async with aiofiles.open(filepath, 'r') as f:
                content = await f.read()
                existing_data = json.loads(content)
        
        # merge new readings with existing
        for utility_type, new_meters in data.items():
            if utility_type not in existing_data:
                existing_data[utility_type] = new_meters
            else:
                # merge readings for each meter
                for new_meter in new_meters:
                    meter_num = new_meter["meterNumber"]
                    existing_meter = next((m for m in existing_data[utility_type] if m["meterNumber"] == meter_num), None)
                    
                    if existing_meter:
                        # get existing timestamps
                        existing_timestamps = {r["timestamp"] for r in existing_meter["readings"]}
                        # add only new readings
                        for reading in new_meter["readings"]:
                            if reading["timestamp"] not in existing_timestamps:
                                existing_meter["readings"].append(reading)
                        # sort by timestamp
                        existing_meter["readings"].sort(key=lambda x: x["timestamp"] or 0)
                    else:
                        existing_data[utility_type].append(new_meter)
        
        # save merged data
        async with aiofiles.open(filepath, "w") as f:
            await f.write(json.dumps(existing_data, indent=2))
        
        _LOGGER.info(f"hsv data updated: {filepath}")
        
    except Exception as e:
        _LOGGER.error(f"failed to save hsv data: {e}")


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
            account_info = await get_account_info(session, username)
            if not account_info:
                _LOGGER.error("failed to get hsv account info")
                return False
            
            data = await collect_usage_data(session, account_info, username, data_period_days, intervals)
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