"""Config flow for Utilities Scraper integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ECOBEE_PASSWORD,
    CONF_ECOBEE_USERNAME,
    CONF_COLLECTION_INTERVAL,
    CONF_DATA_PERIOD_DAYS,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_HSV_PASSWORD,
    CONF_HSV_USERNAME,
    DEFAULT_COLLECTION_INTERVAL,
    DEFAULT_DATA_PERIOD_DAYS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HSV_USERNAME): str,
        vol.Required(CONF_HSV_PASSWORD): str,
        vol.Required(CONF_ECOBEE_USERNAME): str,
        vol.Required(CONF_ECOBEE_PASSWORD): str,
        vol.Optional(CONF_DATA_PERIOD_DAYS, default=DEFAULT_DATA_PERIOD_DAYS): vol.All(
            int, vol.Range(min=-1)
        ),
        vol.Optional(CONF_COLLECTION_INTERVAL, default=DEFAULT_COLLECTION_INTERVAL): int,
        vol.Optional(CONF_HA_URL): str,
        vol.Optional(CONF_HA_TOKEN): str,
    }
)


class UtilitiesScraperConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Utilities Scraper."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate credentials by attempting to connect
                await self._test_credentials(user_input)
                
                # Create entry
                return self.async_create_entry(
                    title="Utilities Scraper",
                    data=user_input,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def _test_credentials(self, user_input: Dict[str, Any]) -> None:
        """Test the provided credentials."""
        from .scrapers.hsv_scraper import test_hsv_connection
        from .scrapers.ecobee_scraper import test_ecobee_connection
        
        hsv_username = user_input[CONF_HSV_USERNAME]
        hsv_password = user_input[CONF_HSV_PASSWORD]
        
        if not await test_hsv_connection(hsv_username, hsv_password):
            raise InvalidAuth("Invalid HSV credentials")
            
        ecobee_username = user_input[CONF_ECOBEE_USERNAME]
        ecobee_password = user_input[CONF_ECOBEE_PASSWORD]
        
        if not await test_ecobee_connection(ecobee_username, ecobee_password):
            raise InvalidAuth("Invalid Ecobee credentials")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""