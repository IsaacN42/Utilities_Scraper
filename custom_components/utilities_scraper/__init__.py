"""The Utilities Scraper integration."""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """set up utilities scraper from config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # test credentials before setting up platforms
    try:
        from .scrapers.hsv_scraper import test_hsv_connection
        from .scrapers.ecobee_scraper import test_ecobee_connection
        
        # test hsv
        hsv_ok = await test_hsv_connection(
            entry.data["hsv_username"],
            entry.data["hsv_password"]
        )
        
        # test ecobee
        ecobee_ok = await test_ecobee_connection(
            entry.data["ecobee_username"],
            entry.data["ecobee_password"]
        )
        
        if not hsv_ok and not ecobee_ok:
            raise ConfigEntryNotReady("failed to connect to both hsv and ecobee")
        
        if not hsv_ok:
            _LOGGER.warning("hsv connection failed, continuing with ecobee only")
        
        if not ecobee_ok:
            _LOGGER.warning("ecobee connection failed, continuing with hsv only")
            
    except Exception as err:
        _LOGGER.error(f"error testing credentials: {err}")
        raise ConfigEntryNotReady(f"credential test failed: {err}")
    
    hass.data[DOMAIN][entry.entry_id] = entry.data
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok