"""Config and options flow for the Nebosvit integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .addressing import normalize_name
from .const import (
    CONF_APP_KEY,
    CONF_BASE_URL,
    CONF_HOUSE,
    CONF_OUTAGE_AREA,
    CONF_POWER_AREA,
    CONF_POWER_QUEUE,
    CONF_REGION_ID,
    CONF_REGION_NAME,
    CONF_SETTLEMENT_ID,
    CONF_SETTLEMENT_NAME,
    CONF_STREET,
    CONF_WHOLE_OBLAST,
    DEFAULT_BASE_URL,
    DOMAIN,
    REQUEST_TIMEOUT,
)
from .entity import entry_config
from .regions import children_options, get_name, oblasts, preload

_LOGGER = logging.getLogger(__name__)

SKIP = "none"
MAX_SETTLEMENT_CHOICES = 50
MAX_STREET_HINTS = 40


class _Steps:
    """Steps shared by setup and options: oblast -> place -> optional outage
    schedule -> optional outages by address. `_finish` ends the flow."""

    _base_url: str
    _app_key: str
    _values: dict[str, Any]

    def _init_steps(self, values: dict[str, Any]) -> None:
        self._values = dict(values)
        self._oblast_id = ""
        self._power_areas: list[dict[str, Any]] = []
        self._power_area: dict[str, Any] | None = None
        self._settlements: list[dict[str, Any]] = []
        self._matches: list[dict[str, Any]] = []
        self._settlement: dict[str, Any] | None = None

    async def _get_json(self, path: str) -> Any:
        """GET from the server; None when it is unreachable or answers no."""
        session = async_get_clientsession(self.hass)
        headers = {"X-App-Key": self._app_key} if self._app_key else {}
        try:
            async with session.get(
                f"{self._base_url.rstrip('/')}{path}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            _LOGGER.debug("GET %s failed during setup", path, exc_info=True)
            return None

    async def async_step_oblast(self, user_input: dict[str, Any] | None = None):
        await self.hass.async_add_executor_job(preload)
        if user_input is not None:
            self._oblast_id = user_input["oblast"]
            return await self.async_step_place()
        current = self._values.get(CONF_REGION_ID, "")
        default = next((o for o in oblasts() if current and (current == o or current in children_options(o))), None)
        field = vol.Required("oblast", default=default) if default else vol.Required("oblast")
        return self.async_show_form(step_id="oblast", data_schema=vol.Schema({field: vol.In(oblasts())}))

    async def async_step_place(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._values[CONF_REGION_ID] = user_input[CONF_REGION_ID]
            self._values[CONF_REGION_NAME] = get_name(user_input[CONF_REGION_ID])
            self._values[CONF_WHOLE_OBLAST] = bool(user_input.get(CONF_WHOLE_OBLAST, False))
            if (abort := await self._check_unique()) is not None:
                return abort
            await self._load_power_areas()
            if not self._power_areas:
                return await self._finish()
            return await self.async_step_power_area()
        options = children_options(self._oblast_id)
        current = self._values.get(CONF_REGION_ID)
        default = current if current in options else self._oblast_id
        return self.async_show_form(
            step_id="place",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION_ID, default=default): vol.In(options),
                    vol.Optional(CONF_WHOLE_OBLAST, default=bool(self._values.get(CONF_WHOLE_OBLAST, False))): bool,
                }
            ),
        )

    async def _check_unique(self):
        return None

    async def _load_power_areas(self) -> None:
        """Outage zones of the chosen oblast; empty when none or the feed is down."""
        doc = await self._get_json("/v1/power") or {}
        self._power_areas = [a for a in doc.get("areas", []) if str(a.get("oblastId")) == self._oblast_id]

    def _area_options(self) -> dict[str, str]:
        options = {SKIP: "—"}
        options.update({a["id"]: f"{a['name']} ({a['operator']})" for a in self._power_areas})
        return options

    async def async_step_power_area(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            choice = user_input[CONF_POWER_AREA]
            self._values[CONF_POWER_AREA] = ""
            self._values[CONF_POWER_QUEUE] = ""
            if choice == SKIP:
                return await self.async_step_outage_area()
            self._power_area = next(a for a in self._power_areas if a["id"] == choice)
            self._values[CONF_POWER_AREA] = choice
            if not self._power_area.get("queues"):
                return await self.async_step_outage_area()
            return await self.async_step_power_queue()
        options = self._area_options()
        current = self._values.get(CONF_POWER_AREA)
        default = current if current in options else SKIP
        return self.async_show_form(
            step_id="power_area",
            data_schema=vol.Schema({vol.Required(CONF_POWER_AREA, default=default): vol.In(options)}),
        )

    async def async_step_power_queue(self, user_input: dict[str, Any] | None = None):
        assert self._power_area is not None
        if user_input is not None:
            self._values[CONF_POWER_QUEUE] = user_input[CONF_POWER_QUEUE]
            return await self.async_step_outage_area()
        queues = {q: q for q in self._power_area["queues"]}
        current = self._values.get(CONF_POWER_QUEUE)
        field = vol.Required(CONF_POWER_QUEUE, default=current) if current in queues else vol.Required(CONF_POWER_QUEUE)
        return self.async_show_form(step_id="power_queue", data_schema=vol.Schema({field: vol.In(queues)}))

    async def async_step_outage_area(self, user_input: dict[str, Any] | None = None):
        """Outages by address: the same zones as the schedule."""
        if user_input is not None:
            choice = user_input[CONF_OUTAGE_AREA]
            if choice == SKIP:
                self._clear_address()
                return await self._finish()
            self._values[CONF_OUTAGE_AREA] = choice
            doc = await self._get_json(f"/v1/outages/{choice}/settlements") or {}
            self._settlements = doc.get("settlements") or []
            if not self._settlements:
                return self.async_show_form(
                    step_id="outage_area",
                    data_schema=self._outage_area_schema(choice),
                    errors={"base": "no_settlements"},
                )
            return await self.async_step_outage_search()
        current = self._values.get(CONF_OUTAGE_AREA) or self._values.get(CONF_POWER_AREA) or SKIP
        return self.async_show_form(step_id="outage_area", data_schema=self._outage_area_schema(current))

    def _outage_area_schema(self, default: str) -> vol.Schema:
        options = self._area_options()
        if default not in options:
            default = SKIP
        return vol.Schema({vol.Required(CONF_OUTAGE_AREA, default=default): vol.In(options)})

    def _clear_address(self) -> None:
        for key in (CONF_OUTAGE_AREA, CONF_SETTLEMENT_ID, CONF_SETTLEMENT_NAME, CONF_STREET, CONF_HOUSE):
            self._values[key] = ""

    async def async_step_outage_search(self, user_input: dict[str, Any] | None = None):
        """The zone may list thousands of settlements: search by name first."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = normalize_name(user_input["query"])
            self._matches = [
                s for s in self._settlements if query and query in normalize_name(s.get("name", ""))
            ][:MAX_SETTLEMENT_CHOICES]
            if self._matches:
                return await self.async_step_outage_settlement()
            errors["base"] = "no_match"
        default = self._values.get(CONF_SETTLEMENT_NAME, "")
        return self.async_show_form(
            step_id="outage_search",
            data_schema=vol.Schema({vol.Required("query", default=default): str}),
            errors=errors,
        )

    async def async_step_outage_settlement(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._settlement = next(s for s in self._matches if s["id"] == user_input[CONF_SETTLEMENT_ID])
            self._values[CONF_SETTLEMENT_ID] = self._settlement["id"]
            self._values[CONF_SETTLEMENT_NAME] = self._settlement["name"]
            return await self.async_step_outage_address()
        options = {
            s["id"]: s["name"] + (f" ({s['qualifier']})" if s.get("qualifier") else "") for s in self._matches
        }
        return self.async_show_form(
            step_id="outage_settlement",
            data_schema=vol.Schema({vol.Required(CONF_SETTLEMENT_ID): vol.In(options)}),
        )

    async def async_step_outage_address(self, user_input: dict[str, Any] | None = None):
        """Street and house stay in Home Assistant; both may be left empty."""
        if user_input is not None:
            self._values[CONF_STREET] = user_input.get(CONF_STREET, "").strip()
            self._values[CONF_HOUSE] = user_input.get(CONF_HOUSE, "").strip()
            return await self._finish()
        streets = (self._settlement or {}).get("streets") or []
        return self.async_show_form(
            step_id="outage_address",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_STREET, default=self._values.get(CONF_STREET, "")): str,
                    vol.Optional(CONF_HOUSE, default=self._values.get(CONF_HOUSE, "")): str,
                }
            ),
            description_placeholders={
                "streets": ", ".join(streets[:MAX_STREET_HINTS]) + ("…" if len(streets) > MAX_STREET_HINTS else "")
                or "—"
            },
        )

    async def _finish(self):
        raise NotImplementedError


class NebosvitConfigFlow(_Steps, config_entries.ConfigFlow, domain=DOMAIN):
    """Server, then the shared steps."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_url = DEFAULT_BASE_URL
        self._app_key = ""
        self._init_steps({})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> NebosvitOptionsFlow:
        return NebosvitOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._base_url = user_input[CONF_BASE_URL].strip()
            self._app_key = user_input.get(CONF_APP_KEY, "").strip()
            session = async_get_clientsession(self.hass)
            headers = {"X-App-Key": self._app_key} if self._app_key else {}
            try:
                async with session.get(
                    f"{self._base_url.rstrip('/')}/v1/snapshot",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status in (401, 403):
                        errors["base"] = "invalid_auth"
                    elif resp.status != 200:
                        errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            if not errors:
                return await self.async_step_oblast()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=self._base_url): str,
                    vol.Optional(CONF_APP_KEY, default=self._app_key): str,
                }
            ),
            errors=errors,
        )

    async def _check_unique(self):
        await self.async_set_unique_id(f"{self._base_url}|{self._values[CONF_REGION_ID]}", raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return None

    async def _finish(self):
        values = {
            CONF_POWER_AREA: "",
            CONF_POWER_QUEUE: "",
            CONF_OUTAGE_AREA: "",
            CONF_SETTLEMENT_ID: "",
            CONF_SETTLEMENT_NAME: "",
            CONF_STREET: "",
            CONF_HOUSE: "",
            CONF_WHOLE_OBLAST: False,
            **self._values,
        }
        if not values.get(CONF_SETTLEMENT_ID):
            values[CONF_OUTAGE_AREA] = ""
        return self.async_create_entry(
            title=values[CONF_REGION_NAME],
            data={CONF_BASE_URL: self._base_url, CONF_APP_KEY: self._app_key, **values},
        )


class NebosvitOptionsFlow(_Steps, config_entries.OptionsFlow):
    """Change the place, the schedule and the address without removing the
    integration; the entry reloads with them."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        config = entry_config(self.config_entry)
        self._base_url = config[CONF_BASE_URL]
        self._app_key = config.get(CONF_APP_KEY, "")
        self._init_steps(config)
        return await self.async_step_oblast()

    async def _finish(self):
        values = {k: v for k, v in self._values.items() if k not in (CONF_BASE_URL, CONF_APP_KEY)}
        if not values.get(CONF_SETTLEMENT_ID):
            values[CONF_OUTAGE_AREA] = ""
        self.hass.config_entries.async_update_entry(self.config_entry, title=values[CONF_REGION_NAME])
        return self.async_create_entry(data=values)
