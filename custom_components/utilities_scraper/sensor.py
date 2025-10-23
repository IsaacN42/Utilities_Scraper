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
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]) -> None:
        """Initialize."""
        self.hass = hass
        self.config = config
        self.data_dir = Path(hass.config.config_dir) / "custom_components" / "utilities_scraper"
        
        # Ensure data directories exist
        (self.data_dir / "data" / "utilities").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "data" / "ecobee").mkdir(parents=True, exist_ok=True)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=config[CONF_COLLECTION_INTERVAL]),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data via library."""
        try:
            # Run data collection
            await self._collect_data()
            
            # Process and return latest data
            return await self._process_latest_data()
            
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _collect_data(self) -> None:
        """Collect data from both sources."""
        # Import scrapers
        from .scrapers.hsv_scraper import collect_hsv_data
        from .scrapers.ecobee_scraper import collect_ecobee_data
        
        # Collect HSV data
        hsv_username = self.config["hsv_username"]
        hsv_password = self.config["hsv_password"]
        data_period_days = self.config[CONF_DATA_PERIOD_DAYS]
        
        await collect_hsv_data(
            hsv_username, 
            hsv_password, 
            data_period_days,
            str(self.data_dir / "data" / "utilities")
        )
        
        # Collect Ecobee data
        ecobee_username = self.config["ecobee_username"]
        ecobee_password = self.config["ecobee_password"]
        
        await collect_ecobee_data(
            ecobee_username,
            ecobee_password,
            data_period_days,
            str(self.data_dir / "data" / "ecobee")
        )

    async def _process_latest_data(self) -> Dict[str, Any]:
        """Process the latest collected data."""
        data = {}
        
        # Process HSV data
        hsv_files = list((self.data_dir / "data" / "utilities").glob("hsu_usage_*.json"))
        if hsv_files:
            latest_hsv = max(hsv_files, key=lambda p: p.stat().st_mtime)
            with open(latest_hsv, 'r') as f:
                hsv_data = json.load(f)
                data.update(self._extract_usage_data(hsv_data))
        
        # Process Ecobee data
        ecobee_files = list((self.data_dir / "data" / "ecobee").glob("ecobee_data_*.json"))
        if ecobee_files:
            latest_ecobee = max(ecobee_files, key=lambda p: p.stat().st_mtime)
            async with aiofiles.open(latest_ecobee, 'r') as f:
                content = await f.read()
                ecobee_data = json.loads(content)
                data.update(self._extract_hvac_data(ecobee_data))
        
        return data

    def _extract_usage_data(self, hsv_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract usage data from HSV JSON."""
        data = {}
        
        for utility_type, meters in hsv_data.items():
            total_usage = 0
            unit = "unknown"
            
            for meter in meters:
                unit = meter.get('unitOfMeasure', unit)
                for reading in meter.get('readings', []):
                    total_usage += reading.get('usage', 0)
            
            # Map to sensor types
            if utility_type == "ELECTRIC":
                data["electric_usage"] = round(total_usage, 2)
            elif utility_type == "GAS":
                data["gas_usage"] = round(total_usage, 2)
            elif utility_type == "WATER":
                data["water_usage"] = round(total_usage, 2)
        
        return data

    def _extract_hvac_data(self, ecobee_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract HVAC data from Ecobee JSON."""
        data = {}
        
        if "THERMOSTAT" in ecobee_data:
            thermostat = ecobee_data["THERMOSTAT"][0]
            readings = thermostat.get("readings", [])
            
            if readings:
                # Calculate runtime percentages
                comp_cool_times = []
                comp_heat_times = []
                
                for reading in readings:
                    data_dict = reading.get("data", {})
                    comp_cool_times.append(float(data_dict.get("compCool1", 0)))
                    comp_heat_times.append(float(data_dict.get("compHeat1", 0)))
                
                # Calculate percentages (5-minute intervals = 300 seconds)
                if comp_cool_times:
                    avg_cool_runtime = sum(comp_cool_times) / len(comp_cool_times)
                    data["compressor_runtime"] = round((avg_cool_runtime / 300) * 100, 1)
                
                if comp_heat_times:
                    avg_heat_runtime = sum(comp_heat_times) / len(comp_heat_times)
                    data["heat_pump_runtime"] = round((avg_heat_runtime / 300) * 100, 1)
                
                # Overall HVAC efficiency (simplified)
                if comp_cool_times and comp_heat_times:
                    total_runtime = (sum(comp_cool_times) + sum(comp_heat_times)) / len(comp_cool_times)
                    data["hvac_efficiency"] = round((total_runtime / 300) * 100, 1)
        
        return data


class UtilitiesScraperSensor(SensorEntity):
    """Representation of a Utilities Scraper sensor."""

    def __init__(
        self,
        coordinator: UtilitiesScraperCoordinator,
        sensor_type: str,
        sensor_config: Dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.sensor_type = sensor_type
        self.sensor_config = sensor_config
        self._attr_name = f"Utilities Scraper {sensor_config['name']}"
        self._attr_unique_id = f"{DOMAIN}_{sensor_type}"
        self._attr_unit_of_measurement = sensor_config["unit"]
        self._attr_icon = sensor_config["icon"]
        self._attr_device_class = sensor_config["device_class"]

    @property
    def state(self) -> Optional[float]:
        """Return the state of the sensor."""
        return self.coordinator.data.get(self.sensor_type)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Utilities Scraper sensors from a config entry."""
    coordinator = UtilitiesScraperCoordinator(hass, config_entry.data)

    # Fetch initial data so we have data when entities are added
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [
            UtilitiesScraperSensor(coordinator, sensor_type, sensor_config)
            for sensor_type, sensor_config in SENSOR_TYPES.items()
        ]
    )
