"""Shared entity base classes."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_REGION_NAME, DOMAIN


def entry_config(entry: ConfigEntry) -> dict:
    """Setup data with the changes made in the options flow on top."""
    return {**entry.data, **entry.options}


class NebosvitAlertEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._config = entry_config(entry)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self._config[CONF_REGION_NAME],
            manufacturer="Nebosvit",
            entry_type=DeviceEntryType.SERVICE,
        )


class TickingEntity(NebosvitAlertEntity):
    """Data fetched every few minutes, but "now" moves every minute: recompute
    locally so a slot or outage boundary is not missed."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, lambda _now: self.async_write_ha_state(), timedelta(minutes=1)
            )
        )
