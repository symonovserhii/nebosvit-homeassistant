"""The Nebosvit integration: air raid alerts, outage schedules and outages by address for Ukraine."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_OUTAGE_AREA,
    CONF_POWER_AREA,
    CONF_POWER_QUEUE,
    CONF_REGION_ID,
    CONF_SETTLEMENT_ID,
    DOMAIN,
)
from .coordinator import AlertsCoordinator, OutagesCoordinator, PowerCoordinator
from .entity import entry_config
from .regions import preload

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.async_add_executor_job(preload)
    data = entry_config(entry)
    app_key = data.get(CONF_APP_KEY) or None

    alerts = AlertsCoordinator(hass, data[CONF_BASE_URL], app_key, data[CONF_REGION_ID])
    await alerts.async_config_entry_first_refresh()
    # Cancelled with the entry: unload and reload stop it.
    entry.async_create_background_task(hass, alerts.listen(), f"{DOMAIN} live {entry.entry_id}")

    power: PowerCoordinator | None = None
    if data.get(CONF_POWER_AREA) and data.get(CONF_POWER_QUEUE):
        power = PowerCoordinator(
            hass, data[CONF_BASE_URL], app_key, data[CONF_POWER_AREA], data[CONF_POWER_QUEUE]
        )
        await power.async_config_entry_first_refresh()

    outages: OutagesCoordinator | None = None
    if data.get(CONF_OUTAGE_AREA) and data.get(CONF_SETTLEMENT_ID):
        outages = OutagesCoordinator(
            hass, data[CONF_BASE_URL], app_key, data[CONF_OUTAGE_AREA], data[CONF_SETTLEMENT_ID]
        )
        await outages.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"alerts": alerts, "power": power, "outages": outages}
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: start over with the new region, schedule or address."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
