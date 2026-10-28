"""Binary sensors for the Nebosvit integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_HOUSE, CONF_REGION_NAME, CONF_STREET, DOMAIN, POWER_MAYBE_OFF, POWER_OFF, STATUS_CLEAR
from .entity import NebosvitAlertEntity, TickingEntity
from .sensor import outage_attributes
from .timeline import matched_outages, outage_is_on, power_state_at


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [AlertActiveSensor(runtime["alerts"], entry)]
    if runtime["power"] is not None:
        entities.append(PowerOffSensor(runtime["power"], entry))
    if runtime["outages"] is not None:
        entities.append(OutageNowSensor(runtime["outages"], entry))
    async_add_entities(entities)


class AlertActiveSensor(NebosvitAlertEntity, BinarySensorEntity):
    """On while any alert concerns the watched region."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "alert_active"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alert_active")

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data.get("known"))

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data.get("known"):
            return None
        return data["status"] != STATUS_CLEAR

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "region": self._config[CONF_REGION_NAME],
            "level": data.get("status"),
            "alerts": data.get("alerts", []),
            "threat_details": data.get("threat_details", []),
            "confirmed_only": data.get("partial", False),
        }


class PowerOffSensor(TickingEntity, BinarySensorEntity):
    """On while the schedule says the light is off; a possible outage only
    shows in `maybe_off`, so automations do not fire on a guess."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "power_off"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_off")

    @property
    def is_on(self) -> bool:
        return power_state_at(self.coordinator.data["schedule"], dt_util.now()) == POWER_OFF

    @property
    def extra_state_attributes(self) -> dict:
        state = power_state_at(self.coordinator.data["schedule"], dt_util.now())
        return {"state": state, "maybe_off": state == POWER_MAYBE_OFF, "schedule_only": True}


class OutageNowSensor(TickingEntity, BinarySensorEntity):
    """On while a planned or emergency outage concerns my address."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "outage_now"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "outage_now")

    def _current(self) -> dict | None:
        now = dt_util.utcnow()
        rows = matched_outages(
            self.coordinator.data.get("outages") or [],
            self._config.get(CONF_STREET),
            self._config.get(CONF_HOUSE),
            now,
        )
        return next((r for r in rows if outage_is_on(r, now)), None)

    @property
    def is_on(self) -> bool:
        return self._current() is not None

    @property
    def extra_state_attributes(self) -> dict:
        current = self._current()
        return outage_attributes(current) if current else {}
