from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS, SERVICE_REFRESH_NOW
from .coordinator import UtilitiesScraperCoordinator


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = UtilitiesScraperCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # optional: create a device so sensors group nicely
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="IsaacN42",
        name="Utilities Scraper",
        model="Desktop Scrapers",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_refresh(_: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    # service is registered once per HA instance
    # (it will refresh all entries)
    if SERVICE_REFRESH_NOW not in hass.services.async_services().get(DOMAIN, {}):
        hass.services.async_register(DOMAIN, SERVICE_REFRESH_NOW, _handle_refresh)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if coordinator:
        coordinator.async_shutdown()
    return ok
