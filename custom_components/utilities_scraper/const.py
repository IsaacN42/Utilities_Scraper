"""Constants for the Utilities Scraper integration."""

DOMAIN = "utilities_scraper"

# Configuration keys
CONF_HSV_USERNAME = "hsv_username"
CONF_HSV_PASSWORD = "hsv_password"
CONF_ECOBEE_USERNAME = "ecobee_username"
CONF_ECOBEE_PASSWORD = "ecobee_password"
CONF_DATA_PERIOD_DAYS = "data_period_days"
CONF_COLLECTION_INTERVAL = "collection_interval"
CONF_HA_URL = "ha_url"
CONF_HA_TOKEN = "ha_token"

# Default values
DEFAULT_DATA_PERIOD_DAYS = 7
DEFAULT_COLLECTION_INTERVAL = 3600  # 1 hour in seconds

# Data directories
DATA_UTILITIES_DIR = "data/utilities"
DATA_ECOBEE_DIR = "data/ecobee"
DATA_REPORTS_DIR = "data/reports"
DATA_PLOTS_DIR = "data/plots"

# Sensor types
SENSOR_TYPES = {
    "electric_usage": {
        "name": "Electric Usage",
        "unit": "kWh",
        "icon": "mdi:lightning-bolt",
        "device_class": "energy",
        "state_class": "total_increasing"
    },
    "gas_usage": {
        "name": "Gas Usage", 
        "unit": "therms",
        "icon": "mdi:fire",
        "device_class": "gas",
        "state_class": "total_increasing"
    },
    "water_usage": {
        "name": "Water Usage",
        "unit": "gal",
        "icon": "mdi:water",
        "device_class": "water",
        "state_class": "total_increasing"
    },
    "hvac_efficiency": {
        "name": "HVAC Efficiency",
        "unit": "%",
        "icon": "mdi:thermometer",
        "device_class": None,
        "state_class": "measurement"
    },
    "compressor_runtime": {
        "name": "AC Compressor Runtime",
        "unit": "%",
        "icon": "mdi:air-conditioner",
        "device_class": None,
        "state_class": "measurement"
    },
    "heat_pump_runtime": {
        "name": "Heat Pump Runtime", 
        "unit": "%",
        "icon": "mdi:heat-pump",
        "device_class": None,
        "state_class": "measurement"
    },
    "last_update": {
        "name": "Last Update",
        "unit": None,
        "icon": "mdi:clock-outline",
        "device_class": "timestamp",
        "state_class": None
    }
}

# File patterns
HSV_FILE_PATTERN = "hsu_usage_*.json"
ECOBEE_FILE_PATTERN = "ecobee_data_*.json"
REPORT_FILE_PATTERN = "energy_report_*.txt"