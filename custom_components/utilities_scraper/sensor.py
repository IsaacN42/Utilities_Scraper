from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UtilitiesScraperCoordinator


@dataclass(frozen=True, kw_only=True)
class UtilitiesSensorDescription(SensorEntityDescription):
    source: str
    key: str


SENSORS: list[UtilitiesSensorDescription] = [
    UtilitiesSensorDescription(
        key="ok",
        name="HSV Status",
        icon="mdi:check-decagram",
        source="hsv",
        native_unit_of_measurement=None,
    ),
    UtilitiesSensorDescription(
        key="last_update",
        name="HSV Last Update",
        icon="mdi:clock-outline",
        source="hsv",
        native_unit_of_measurement=None,
    ),
    UtilitiesSensorDescription(
        key="added",
        name="HSV Added Readings (Last Run)",
        icon="mdi:plus-circle-outline",
        source="hsv",
        native_unit_of_measurement=None,
    ),
    UtilitiesSensorDescription(
        key="ok",
        name="Ecobee Status",
        icon="mdi:check-decagram",
        source="ecobee",
        native_unit_of_measurement=None,
    ),
    UtilitiesSensorDescription(
        key="last_update",
        name="Ecobee Last Update",
        icon="mdi:clock-outline",
        source="ecobee",
        native_unit_of_measurement=None,
    ),
    UtilitiesSensorDescription(
        key="added",
        name="Ecobee Added Readings (Last Run)",
        icon="mdi:plus-circle-outline",
        source="ecobee",
        native_unit_of_measurement=None,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UtilitiesScraperCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[UtilitiesScraperSensor] = []
    for desc in SENSORS:
        entities.append(UtilitiesScraperSensor(coordinator, entry, desc))

    async_add_entities(entities)


class UtilitiesScraperSensor(CoordinatorEntity[UtilitiesScraperCoordinator], SensorEntity):
    entity_description: UtilitiesSensorDescription

    def __init__(
        self,
        coordinator: UtilitiesScraperCoordinator,
        entry: ConfigEntry,
        description: UtilitiesSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description

        self._attr_unique_id = f"{entry.entry_id}_{description.source}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Utilities Scraper",
        }

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        src = data.get(self.entity_description.source, {}) if isinstance(data, dict) else {}
        if not isinstance(src, dict):
            return None

        val = src.get(self.entity_description.key)

        # present boolean status as "ok"/"fail" for UI clarity
        if self.entity_description.key == "ok":
            if val is True:
                return "ok"
            if val is False:
                return "fail"
            return None

        return val
