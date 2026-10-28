"""The Nebosvit integration: air raid alerts, outage schedules and outages by address for Ukraine."""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_OUTAGE_AREA,
    CONF_POWER_AREA,
    CONF_POWER_QUEUE,
    CONF_REGION_ID,
    CONF_SETTLEMENT_ID,
    CONF_WHOLE_OBLAST,
    DOMAIN,
)
from .coordinator import AlertsCoordinator, OutagesCoordinator, PowerCoordinator
from .entity import entry_config
from .regions import preload

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]
# Set up from the UI only; async_setup exists just to serve the cards.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

STATIC_URL = "/nebosvit_static"
CARDS_JS = f"{STATIC_URL}/nebosvit-cards.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard cards and map outlines that ship with the integration."""
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(frontend_dir), cache_headers=True)]
    )
    # The version in the query string makes browsers reload the cards after an update.
    version = await hass.async_add_executor_job(_manifest_version)
    add_extra_js_url(hass, f"{CARDS_JS}?v={version}")
    return True


def _manifest_version() -> str:
    return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.async_add_executor_job(preload)
    data = entry_config(entry)
    app_key = data.get(CONF_APP_KEY) or None

    alerts = AlertsCoordinator(
        hass, data[CONF_BASE_URL], app_key, data[CONF_REGION_ID], bool(data.get(CONF_WHOLE_OBLAST, False))
    )
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
