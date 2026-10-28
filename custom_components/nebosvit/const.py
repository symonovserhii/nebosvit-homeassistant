"""Constants for the Nebosvit integration."""
from datetime import timedelta

DOMAIN = "nebosvit"

CONF_BASE_URL = "base_url"
CONF_APP_KEY = "app_key"
CONF_REGION_ID = "region_id"
CONF_REGION_NAME = "region_name"
# Count any alert in the oblast, not only those touching the place.
CONF_WHOLE_OBLAST = "whole_oblast"
CONF_POWER_AREA = "power_area"
CONF_POWER_QUEUE = "power_queue"
CONF_OUTAGE_AREA = "outage_area"
CONF_SETTLEMENT_ID = "settlement_id"
CONF_SETTLEMENT_NAME = "settlement_name"
CONF_STREET = "street"
CONF_HOUSE = "house"

DEFAULT_BASE_URL = "https://alarm-api.symonov.com"

# The server answers 304 for an unchanged snapshot, so this stays cheap. Changes
# arrive at once over /v1/snapshot/ws; polling is the fallback.
ALERTS_SCAN_INTERVAL = timedelta(seconds=30)
LIVE_RECONNECT_MIN = 3
LIVE_RECONNECT_MAX = 60
# Schedules are refreshed on the server every 5-10 minutes.
POWER_SCAN_INTERVAL = timedelta(minutes=5)
# Outages by address: emergencies change every 15-30 minutes on the server.
OUTAGES_SCAN_INTERVAL = timedelta(minutes=15)

REQUEST_TIMEOUT = 15
KYIV_TZ = "Europe/Kyiv"

STATUS_CLEAR = "clear"
STATUS_YELLOW = "yellow"
STATUS_RED = "red"

# Alert types ordered by how much attention they deserve, most urgent first.
TYPE_PRIORITY = ["nuclear", "chemical", "air", "artillery", "urban_fights", "unknown"]
TYPE_NONE = "none"

# Power states and schedule day statuses live with the logic that computes them.
from .timeline import (  # noqa: E402
    DAY_STATUSES,
    POWER_MAYBE_OFF,
    POWER_OFF,
    POWER_ON,
    POWER_UNKNOWN,
)
