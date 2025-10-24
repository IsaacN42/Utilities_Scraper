"""Sensor platform for Utilities Scraper integration."""
import aiofiles
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_COLLECTION_INTERVAL,
    CONF_DATA_PERIOD_DAYS,
    DATA_ECOBEE_DIR,
    DATA_UTILITIES_DIR,
    DOMAIN,
    SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class UtilitiesScraperCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]) -> None:
        """initialize."""
        self.hass = hass
        self.config = config
        self.data_dir = Path(hass.config.config_dir) / "custom_components" / "utilities_scraper"
        self._first_refresh = True
        self._last_collection = None  # add this
        
        # ensure data directories exist
        (self.data_dir / "data" / "utilities").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "data" / "ecobee").mkdir(parents=True, exist_ok=True)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=config[CONF_COLLECTION_INTERVAL]),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """update data via library."""
        try:
            # skip data collection on first refresh, just read existing files
            if not self._first_refresh:
                await self._collect_data()
            else:
                _LOGGER.info("first refresh - reading existing data files")
                self._first_refresh = False
            
            # process and return latest data
            return await self._process_latest_data()
            
        except Exception as err:
            _LOGGER.warning(f"update failed: {err}")
            # return empty dict instead of raising
            return {}
    
    async def _collect_data(self) -> None:
        """collect data from both sources."""
        from .scrapers.hsv_scraper import collect_hsv_data
        from .scrapers.ecobee_scraper import collect_ecobee_data
        
        hsv_username = self.config["hsv_username"]
        hsv_password = self.config["hsv_password"]
        ecobee_username = self.config["ecobee_username"]
        ecobee_password = self.config["ecobee_password"]
        
        # on first run, get full history based on DATA_PERIOD_DAYS
        # on subsequent runs, only get data since last collection
        if self._last_collection is None:
            data_period_days = self.config[CONF_DATA_PERIOD_DAYS]
            _LOGGER.info(f"first collection - fetching {data_period_days} days of history")
        else:
            # calculate days since last collection
            days_since = (datetime.now() - self._last_collection).days + 1
            data_period_days = max(1, days_since)
            _LOGGER.info(f"incremental collection - fetching {data_period_days} days since last run")
        
        # collect both
        try:
            await collect_hsv_data(
                hsv_username, 
                hsv_password, 
                data_period_days,
                str(self.data_dir / "data" / "utilities")
            )
        except Exception as e:
            _LOGGER.warning(f"hsv collection failed: {e}")
        
        try:
            await collect_ecobee_data(
                ecobee_username,
                ecobee_password,
                data_period_days,
                str(self.data_dir / "data" / "ecobee")
            )
        except Exception as e:
            _LOGGER.warning(f"ecobee collection failed: {e}")
        
        # update last collection time
        self._last_collection = datetime.now()
    
    async def _process_latest_data(self) -> Dict[str, Any]:
        """process the latest collected data."""
        data = {}
        
        # process hsv data - new single file
        try:
            hsv_file = self.data_dir / "data" / "utilities" / "hsv_usage_historical.json"
            if hsv_file.exists():
                async with aiofiles.open(hsv_file, 'r') as f:
                    content = await f.read()
                    hsv_data = json.loads(content)
                    data.update(self._extract_usage_data(hsv_data))
        except Exception as e:
            _LOGGER.warning(f"failed to process hsv data: {e}")
        
        # process ecobee data - new single file
        try:
            ecobee_file = self.data_dir / "data" / "ecobee" / "ecobee_data_historical.json"
            if ecobee_file.exists():
                async with aiofiles.open(ecobee_file, 'r') as f:
                    content = await f.read()
                    ecobee_data = json.loads(content)
                    data.update(self._extract_hvac_data(ecobee_data))
        except Exception as e:
            _LOGGER.warning(f"failed to process ecobee data: {e}")
        
        return data

    def _extract_usage_data(self, hsv_data: Dict[str, Any]) -> Dict[str, Any]:
        """extract usage data from hsv json - show totals for period."""
        data = {}
        
        for utility_type, meters in hsv_data.items():
            # calculate total for last 24 hours
            cutoff = datetime.now() - timedelta(hours=24)
            cutoff_ms = int(cutoff.timestamp() * 1000)
            
            total_usage = 0
            unit = "unknown"
            
            for meter in meters:
                unit = meter.get('unitOfMeasure', unit)
                for reading in meter.get('readings', []):
                    if reading.get('timestamp', 0) >= cutoff_ms:
                        total_usage += reading.get('usage', 0)
            
            # map to sensor types
            if utility_type == "ELECTRIC":
                data["electric_usage"] = round(total_usage, 2)
            elif utility_type == "GAS":
                data["gas_usage"] = round(total_usage, 2)
            elif utility_type == "WATER":
                data["water_usage"] = round(total_usage, 2)
        
        return data

    def _extract_hvac_data(self, ecobee_data: Dict[str, Any]) -> Dict[str, Any]:
        """extract hvac data from ecobee json."""
        data = {}
        
        if "THERMOSTAT" in ecobee_data:
            thermostat = ecobee_data["THERMOSTAT"][0]
            readings = thermostat.get("readings", [])
            
            if readings:
                # calculate runtime percentages
                comp_cool_times = []
                comp_heat_times = []
                
                for reading in readings:
                    data_dict = reading.get("data", {})
                    
                    # safely convert to float, default to 0 if empty or invalid
                    try:
                        cool_val = data_dict.get("compCool1", "0")
                        cool_val = 0 if cool_val == "" else float(cool_val)
                        comp_cool_times.append(cool_val)
                    except (ValueError, TypeError):
                        comp_cool_times.append(0)
                    
                    try:
                        heat_val = data_dict.get("compHeat1", "0")
                        heat_val = 0 if heat_val == "" else float(heat_val)
                        comp_heat_times.append(heat_val)
                    except (ValueError, TypeError):
                        comp_heat_times.append(0)
                
                # calculate percentages (5-minute intervals = 300 seconds)
                if comp_cool_times:
                    avg_cool_runtime = sum(comp_cool_times) / len(comp_cool_times)
                    if avg_cool_runtime > 0:
                        data["compressor_runtime"] = round((avg_cool_runtime / 300) * 100, 1)
                
                if comp_heat_times:
                    avg_heat_runtime = sum(comp_heat_times) / len(comp_heat_times)
                    if avg_heat_runtime > 0:
                        data["heat_pump_runtime"] = round((avg_heat_runtime / 300) * 100, 1)
                
                # overall hvac efficiency (simplified)
                if comp_cool_times and comp_heat_times:
                    total_runtime = (sum(comp_cool_times) + sum(comp_heat_times)) / len(comp_cool_times)
                    if total_runtime > 0:
                        data["hvac_efficiency"] = round((total_runtime / 300) * 100, 1)
        
        return data


class UtilitiesScraperSensor(SensorEntity):
    """representation of a utilities scraper sensor."""
    
    def __init__(
        self,
        coordinator: UtilitiesScraperCoordinator,
        sensor_type: str,
        sensor_config: Dict[str, Any],
    ) -> None:
        """initialize the sensor."""
        self.coordinator = coordinator
        self.sensor_type = sensor_type
        self.sensor_config = sensor_config
        self._attr_name = f"Utilities Scraper {sensor_config['name']}"
        self._attr_unique_id = f"{DOMAIN}_{sensor_type}"
        self._attr_unit_of_measurement = sensor_config["unit"]
        self._attr_icon = sensor_config["icon"]
        self._attr_device_class = sensor_config["device_class"]
        self._attr_state_class = sensor_config.get("state_class")  # add this line
    
    @property
    def state(self) -> Optional[float]:
        """return the state of the sensor."""
        return self.coordinator.data.get(self.sensor_type)
    
    @property
    def available(self) -> bool:
        """return true if entity is available."""
        return self.coordinator.last_update_success


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """set up utilities scraper sensors from a config entry."""
    coordinator = UtilitiesScraperCoordinator(hass, config_entry.data)
    
    # fetch initial data so we have data when entities are added
    await coordinator.async_config_entry_first_refresh()
    
    async_add_entities(
        [
            UtilitiesScraperSensor(coordinator, sensor_type, sensor_config)
            for sensor_type, sensor_config in SENSOR_TYPES.items()
        ]
    )