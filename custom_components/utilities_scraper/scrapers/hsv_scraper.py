"""HSV Utilities scraper for Home Assistant integration."""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://hsvutil.smarthub.coop"


def convert_interval(interval: str) -> str:
    """Convert interval to API format."""
    if interval == "15_MIN":
        return "FIFTEEN_MINUTE"
    return interval


async def test_hsv_connection(username: str, password: str) -> bool:
    """Test HSV connection with provided credentials."""
    try:
        async with aiohttp.ClientSession() as session:
            # Test login
            async with session.post(
                f"{BASE_URL}/login",
                data={"username": username, "password": password},
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True
            ) as response:
                if not ("/ui/" in str(response.url) or "dashboard" in str(response.url).lower()):
                    return False
                
            # Test OAuth token
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
        _LOGGER.error("HSV connection test failed: %s", e)
        return False


async def create_session(username: str, password: str) -> Optional[aiohttp.ClientSession]:
    """Create authenticated session."""
    session = aiohttp.ClientSession()
    
    try:
        # Login
        async with session.post(
            f"{BASE_URL}/login",
            data={"username": username, "password": password},
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True
        ) as response:
            if not ("/ui/" in str(response.url) or "dashboard" in str(response.url).lower()):
                await session.close()
                return None
            _LOGGER.debug("HSV login successful")
        
        # Get OAuth token
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
            _LOGGER.debug("HSV OAuth token obtained")
            return session
            
    except Exception as e:
        _LOGGER.error("Failed to create HSV session: %s", e)
        await session.close()
        return None


async def get_account_info(session: aiohttp.ClientSession) -> Optional[dict]:
    """Get account and service location info."""
    try:
        async with session.get(f"{BASE_URL}/services/secured/accounts") as response:
            if response.status != 200:
                return None
            
            accounts = await response.json()
            account_number = str(accounts[0]["account"])
            
            # Get service locations
            async with session.get(
                f"{BASE_URL}/services/secured/accounts/{account_number}/service-locations"
            ) as response:
                if response.status != 200:
                    return None
                
                service_locations = await response.json()
                return {
                    "account_number": account_number,
                    "service_locations": service_locations
                }
                
    except Exception as e:
        _LOGGER.error("Failed to get account info: %s", e)
        return None


async def collect_usage_data(
    session: aiohttp.ClientSession,
    account_info: dict,
    data_period_days: int,
    intervals: dict
) -> Optional[dict]:
    """Collect usage data for all utilities."""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=data_period_days)
        
        payload = {
            "accountNumber": account_info["account_number"],
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "serviceLocationIds": [loc["id"] for loc in account_info["service_locations"]],
            "interval": "HOURLY"  # Default to hourly for simplicity
        }
        
        # Poll for data
        async with session.post(
            f"{BASE_URL}/services/secured/utility-usage/poll",
            json=payload
        ) as response:
            if response.status != 200:
                return None
            
            data = await response.json()
            
            # Poll until complete
            while data.get("status") == "IN_PROGRESS":
                await asyncio.sleep(2)
                async with session.post(
                    f"{BASE_URL}/services/secured/utility-usage/poll",
                    json=payload
                ) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
            
            return process_usage_data(data)
            
    except Exception as e:
        _LOGGER.error("Failed to collect usage data: %s", e)
        return None


def process_usage_data(data: dict) -> dict:
    """Process raw usage data into structured format."""
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
    """Save data to JSON file in specified directory."""
    try:
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hsu_usage_{timestamp}.json"
        filepath = data_path / filename
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        _LOGGER.info("HSV data saved to %s", filepath)
        
    except Exception as e:
        _LOGGER.error("Failed to save HSV data: %s", e)


async def collect_hsv_data(
    username: str,
    password: str,
    data_period_days: int,
    data_dir: str,
    intervals: Optional[dict] = None
) -> bool:
    """Main function to collect HSV data."""
    if intervals is None:
        intervals = {
            "ELECTRIC": "HOURLY",
            "GAS": "HOURLY",
            "WATER": "MONTHLY"
        }
    
    try:
        # Create session
        session = await create_session(username, password)
        if not session:
            _LOGGER.error("Failed to create HSV session")
            return False
        
        try:
            # Get account info
            account_info = await get_account_info(session)
            if not account_info:
                _LOGGER.error("Failed to get HSV account info")
                return False
            
            # Collect usage data
            data = await collect_usage_data(session, account_info, data_period_days, intervals)
            if not data:
                _LOGGER.error("Failed to collect HSV usage data")
                return False
            
            # Save data
            await save_data(data, data_dir)
            return True
            
        finally:
            await session.close()
            
    except Exception as e:
        _LOGGER.error("HSV data collection failed: %s", e)
        return False
