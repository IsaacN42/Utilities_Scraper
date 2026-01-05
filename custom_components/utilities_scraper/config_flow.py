from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HSV_USERNAME,
    CONF_HSV_PASSWORD,
    CONF_ECOBEE_USERNAME,
    CONF_ECOBEE_PASSWORD,
    CONF_ECOBEE_2FA_CODE,
)
from .scrapers.hsv_incremental import hsv_test_login
from .scrapers.ecobee_incremental import ecobee_test_login


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HSV_USERNAME): str,
        vol.Required(CONF_HSV_PASSWORD): str,
        vol.Required(CONF_ECOBEE_USERNAME): str,
        vol.Required(CONF_ECOBEE_2FA_CODE): str,
        vol.Required(CONF_ECOBEE_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._temp: dict[str, Any] = {}
        self._hsv_ok: bool = False
        self._ecobee_ok: bool = False
        self._hsv_detail: str = ""
        self._ecobee_detail: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        self._temp = dict(user_input)
        self._hsv_ok = False
        self._ecobee_ok = False
        self._hsv_detail = ""
        self._ecobee_detail = ""

        return await self.async_step_actions()

    async def async_step_actions(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        desc = (
            f"HSV: {'✅ verified' if self._hsv_ok else '❌ not verified'}"
            + (f" ({self._hsv_detail})" if self._hsv_detail else "")
            + "\n"
            f"Ecobee: {'✅ verified' if self._ecobee_ok else '❌ not verified'}"
            + (f" ({self._ecobee_detail})" if self._ecobee_detail else "")
            + "\n\n"
            "Choose an action:"
        )

        return self.async_show_menu(
            step_id="actions",
            menu_options=["test_hsv", "test_ecobee", "ecobee_tutorial", "finish"],
            description=desc,
        )

    async def async_step_test_hsv(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        missing = [k for k in (CONF_HSV_USERNAME, CONF_HSV_PASSWORD) if not self._temp.get(k)]
        if missing:
            return self.async_show_form(
                step_id="test_hsv_result",
                description=f"Missing fields: {', '.join(missing)}",
            )

        ok, detail = await self.hass.async_add_executor_job(
            hsv_test_login,
            self._temp[CONF_HSV_USERNAME],
            self._temp[CONF_HSV_PASSWORD],
        )

        self._hsv_ok = bool(ok)
        self._hsv_detail = detail or ("ok" if ok else "failed")

        return self.async_show_form(
            step_id="test_hsv_result",
            description="✅ HSV login verified." if ok else f"❌ HSV login failed: {detail}",
        )

    async def async_step_test_hsv_result(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_actions()

    async def async_step_test_ecobee(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        missing = [
            k
            for k in (CONF_ECOBEE_USERNAME, CONF_ECOBEE_PASSWORD, CONF_ECOBEE_2FA_CODE)
            if not self._temp.get(k)
        ]
        if missing:
            return self.async_show_form(
                step_id="test_ecobee_result",
                description=f"Missing fields: {', '.join(missing)}",
            )

        ok, detail = await self.hass.async_add_executor_job(
            ecobee_test_login,
            self._temp[CONF_ECOBEE_USERNAME],
            self._temp[CONF_ECOBEE_PASSWORD],
            self._temp[CONF_ECOBEE_2FA_CODE],
        )

        self._ecobee_ok = bool(ok)
        self._ecobee_detail = detail or ("ok" if ok else "failed")

        return self.async_show_form(
            step_id="test_ecobee_result",
            description="✅ Ecobee login verified." if ok else f"❌ Ecobee login failed: {detail}",
        )

    async def async_step_test_ecobee_result(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_actions()

    async def async_step_ecobee_tutorial(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="ecobee_tutorial_done",
            description=(
                "Ecobee 2FA setup (app-only):\n"
                "1) Open the Ecobee mobile app\n"
                "2) Go to Account/Security\n"
                "3) Enable app-based 2FA\n"
                "4) Generate a current 2FA code\n"
                "5) Enter the code in this integration and run “Test Ecobee”\n\n"
                "Notes:\n"
                "- The code expires quickly; test immediately after generating it.\n"
            ),
        )

    async def async_step_ecobee_tutorial_done(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_actions()

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # enforce: both tested successfully
        blockers: list[str] = []
        if not self._hsv_ok:
            blockers.append("HSV not verified (run Test HSV)")
        if not self._ecobee_ok:
            blockers.append("Ecobee not verified (run Test Ecobee)")

        if blockers:
            return self.async_show_form(
                step_id="finish_blocked",
                description="Cannot finish:\n- " + "\n- ".join(blockers),
            )

        return self.async_create_entry(title="Utilities Scraper", data=self._temp)

    async def async_step_finish_blocked(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_actions()
