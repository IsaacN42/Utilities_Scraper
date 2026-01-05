from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DEFAULT_POLL_MINUTES,
    CONF_HSV_USERNAME,
    CONF_HSV_PASSWORD,
    CONF_ECOBEE_USERNAME,
    CONF_ECOBEE_PASSWORD,
    CONF_ECOBEE_2FA_CODE,
)
from .scrapers.hsv_incremental import run_hsv_incremental
from .scrapers.ecobee_incremental import run_ecobee_incremental


class UtilitiesScraperCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        super().__init__(
            hass,
            logger=None,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=DEFAULT_POLL_MINUTES),
        )

    def _entry_base_dir(self) -> Path:
        base = Path(self.hass.config.path(DOMAIN, self.entry.entry_id))
        base.mkdir(parents=True, exist_ok=True)
        return base

    async def _async_update_data(self) -> dict[str, Any]:
        base = self._entry_base_dir()

        hsv_data_file = base / "hsv_current.json"
        hsv_token_file = base / "hsv_token.json"

        ecobee_data_file = base / "ecobee_current.json"
        ecobee_session_file = base / "ecobee_session.json"
        ecobee_token_file = base / "ecobee_token.json"

        hsv_username = self.entry.data[CONF_HSV_USERNAME]
        hsv_password = self.entry.data[CONF_HSV_PASSWORD]

        ecobee_username = self.entry.data[CONF_ECOBEE_USERNAME]
        ecobee_password = self.entry.data[CONF_ECOBEE_PASSWORD]
        ecobee_2fa = self.entry.data[CONF_ECOBEE_2FA_CODE]

        try:
            hsv_result = await self.hass.async_add_executor_job(
                run_hsv_incremental,
                hsv_username,
                hsv_password,
                str(hsv_data_file),
                str(hsv_token_file),
                False,  # test_only
            )

            ecobee_result = await self.hass.async_add_executor_job(
                run_ecobee_incremental,
                ecobee_username,
                ecobee_password,
                ecobee_2fa,
                str(ecobee_data_file),
                str(ecobee_session_file),
                str(ecobee_token_file),
                True,   # headless
                False,  # test_only
            )

            return {
                "hsv": hsv_result,
                "ecobee": ecobee_result,
            }
        except Exception as e:
            raise UpdateFailed(str(e)) from e

    def async_shutdown(self) -> None:
        # placeholder if you later want to close persistent browser resources
        return
