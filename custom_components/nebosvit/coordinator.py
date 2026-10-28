"""Data coordinators for the Nebosvit integration."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ALERTS_SCAN_INTERVAL,
    DOMAIN,
    LIVE_RECONNECT_MAX,
    LIVE_RECONNECT_MIN,
    OUTAGES_SCAN_INTERVAL,
    POWER_SCAN_INTERVAL,
    REQUEST_TIMEOUT,
    STATUS_CLEAR,
    STATUS_RED,
    STATUS_YELLOW,
    TYPE_NONE,
    TYPE_PRIORITY,
)
from .regions import alert_matches
from .timeline import build_timeline

_LOGGER = logging.getLogger(__name__)


def _headers(app_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if app_key:
        headers["X-App-Key"] = app_key
    return headers


class _EtagFeed:
    """GET a JSON document with ETag support; keeps the last good body."""

    def __init__(self, hass: HomeAssistant, base_url: str, path: str, app_key: str | None) -> None:
        self._session = async_get_clientsession(hass)
        self._url = f"{base_url.rstrip('/')}{path}"
        self._headers = _headers(app_key)
        self._etag: str | None = None
        self._body: dict[str, Any] | None = None
        # When the server last confirmed the data fresh (X-Data-Updated-At),
        # or failing that when it last answered.
        self.updated_at: datetime | None = None

    async def fetch(self) -> dict[str, Any]:
        headers = dict(self._headers)
        if self._etag and self._body is not None:
            headers["If-None-Match"] = self._etag
        try:
            async with self._session.get(
                self._url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as resp:
                if resp.status in (401, 403):
                    raise UpdateFailed("The server rejected the app key")
                if resp.status == 404:
                    raise UpdateFailed(f"Not found: {self._url}")
                if resp.status == 429:
                    raise UpdateFailed("Rate limited by the server")
                if resp.status not in (200, 304) or (resp.status == 304 and self._body is None):
                    raise UpdateFailed(f"HTTP {resp.status} from {self._url}")
                stamp = resp.headers.get("X-Data-Updated-At")
                self.updated_at = (dt_util.parse_datetime(stamp) if stamp else None) or dt_util.utcnow()
                if resp.status == 304:
                    return self._body
                self._body = await resp.json()
                self._etag = resp.headers.get("ETag")
                return self._body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Cannot reach the server: {err}") from err


def _severity(alert: dict) -> str:
    return STATUS_RED if alert.get("severity", "red") == "red" else STATUS_YELLOW


class AlertsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Alert state for one watched region.

    The server announces every new snapshot over /v1/snapshot/ws; `listen`
    refreshes at once on it. Polling stays as the fallback for a dropped socket.
    """

    def __init__(self, hass: HomeAssistant, base_url: str, app_key: str | None, region_id: str) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} alerts {region_id}", update_interval=ALERTS_SCAN_INTERVAL
        )
        self.region_id = region_id
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key
        self._feed = _EtagFeed(hass, base_url, "/v1/snapshot", app_key)
        self._version: int | None = None
        self.live = False

    async def listen(self) -> None:
        """Follow /v1/snapshot/ws until cancelled, reconnecting with backoff."""
        session = async_get_clientsession(self.hass)
        url = self._base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/snapshot/ws"
        delay = LIVE_RECONNECT_MIN
        while True:
            try:
                async with session.ws_connect(url, headers=_headers(self._app_key), heartbeat=30) as ws:
                    self.live = True
                    delay = LIVE_RECONNECT_MIN
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        try:
                            version = int(json.loads(msg.data)["version"])
                        except (ValueError, KeyError, TypeError):
                            continue
                        if version != self._version:
                            await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Live socket: %s", err)
            finally:
                self.live = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, LIVE_RECONNECT_MAX)

    async def _async_update_data(self) -> dict[str, Any]:
        snapshot = await self._feed.fetch()
        self._version = snapshot.get("version")
        base = {"updated_at": self._feed.updated_at, "version": self._version}
        raw = snapshot.get("alerts")
        if raw is None:
            # The server has no alert source right now: unknown, not "all clear".
            return {**base, "known": False, "status": None}

        matching = [a for a in raw if alert_matches(self.region_id, a)]
        if not matching:
            return {
                **base,
                "known": True,
                "status": STATUS_CLEAR,
                "type": TYPE_NONE,
                "types": [],
                "threats": [],
                "threat_details": [],
                "since": None,
                "alerts": [],
                "partial": bool(snapshot.get("alertsPartial")),
            }

        status = STATUS_RED if any(_severity(a) == STATUS_RED for a in matching) else STATUS_YELLOW
        types = {str(a.get("type", "UNKNOWN")).lower() for a in matching}
        primary = next((t for t in TYPE_PRIORITY if t in types), "unknown")
        threats = sorted({str(t).lower() for a in matching for t in (a.get("threats") or [])})
        started = [
            parsed
            for parsed in (dt_util.parse_datetime(a.get("startedAt", "")) for a in matching)
            if parsed
        ]
        return {
            **base,
            "known": True,
            "status": status,
            "type": primary,
            "types": sorted(types),
            "threats": threats,
            "threat_details": [
                _detail(d, a.get("regionId")) for a in matching for d in (a.get("threatDetails") or [])
            ],
            "since": min(started) if started else None,
            "alerts": [
                {
                    "region_id": a.get("regionId"),
                    "level": a.get("level"),
                    "type": a.get("type"),
                    "severity": a.get("severity"),
                    "started_at": a.get("startedAt"),
                    "note": a.get("note"),
                    "threat_details": [_detail(d) for d in (a.get("threatDetails") or [])],
                }
                for a in matching
            ],
            "partial": bool(snapshot.get("alertsPartial")),
        }


def _detail(d: dict, region_id: str | None = None) -> dict[str, Any]:
    out = {
        "type": d.get("type"),
        "severity": d.get("severity"),
        "message": d.get("message"),
        "started_at": d.get("startedAt"),
    }
    if region_id is not None:
        out["region_id"] = region_id
    return out


class PowerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Outage schedule (GPV) for one area and queue."""

    def __init__(
        self, hass: HomeAssistant, base_url: str, app_key: str | None, area_id: str, queue: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} power {area_id}", update_interval=POWER_SCAN_INTERVAL
        )
        self.area_id = area_id
        self.queue = queue
        self._feed = _EtagFeed(hass, base_url, "/v1/power", app_key)

    async def _async_update_data(self) -> dict[str, Any]:
        doc = await self._feed.fetch()
        area = next((a for a in doc.get("areas", []) if a.get("id") == self.area_id), None)
        if area is None:
            raise UpdateFailed(f"Area {self.area_id} is not in the schedule feed")
        return {"area": area, "schedule": build_timeline(area, self.queue)}


class OutagesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Planned and emergency outages of one settlement. The street and house
    stay in Home Assistant: the server only sees which settlement is asked."""

    def __init__(
        self, hass: HomeAssistant, base_url: str, app_key: str | None, area_id: str, settlement_id: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} outages {area_id}", update_interval=OUTAGES_SCAN_INTERVAL
        )
        self._feed = _EtagFeed(
            hass, base_url, f"/v1/outages/{area_id}/settlements/{settlement_id}", app_key
        )

    async def _async_update_data(self) -> dict[str, Any]:
        return await self._feed.fetch()
