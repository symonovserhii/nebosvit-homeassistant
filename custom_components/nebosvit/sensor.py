"""Sensors for the Nebosvit integration."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOUSE,
    CONF_POWER_QUEUE,
    CONF_SETTLEMENT_NAME,
    CONF_STREET,
    DAY_STATUSES,
    DOMAIN,
    POWER_MAYBE_OFF,
    POWER_OFF,
    POWER_ON,
    POWER_UNKNOWN,
    STATUS_CLEAR,
    STATUS_RED,
    STATUS_YELLOW,
    TYPE_NONE,
    TYPE_PRIORITY,
)
from .entity import NebosvitAlertEntity, TickingEntity
from .timeline import (
    day_intervals,
    day_status,
    kyiv_date,
    matched_outages,
    minutes_on_day,
    next_power_change,
    next_transition_to,
    outage_is_on,
    power_state_at,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    alerts = runtime["alerts"]
    entities: list[SensorEntity] = [
        AlertStatusSensor(alerts, entry),
        AlertTypeSensor(alerts, entry),
        AlertSinceSensor(alerts, entry),
        LastUpdateSensor(alerts, entry),
    ]
    if (power := runtime["power"]) is not None:
        entities += [
            PowerStateSensor(power, entry),
            PowerNextChangeSensor(power, entry),
            PowerNextOffSensor(power, entry),
            PowerNextOnSensor(power, entry),
            PowerOffTodaySensor(power, entry),
            ScheduleDaySensor(power, entry, tomorrow=False),
            ScheduleDaySensor(power, entry, tomorrow=True),
        ]
    if (outages := runtime["outages"]) is not None:
        entities.append(NextOutageSensor(outages, entry))
    async_add_entities(entities)


class _AlertSensor(NebosvitAlertEntity, SensorEntity):
    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data.get("known"))


class AlertStatusSensor(_AlertSensor):
    """clear / yellow / red for the watched region."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_CLEAR, STATUS_YELLOW, STATUS_RED]
    _attr_translation_key = "alert_status"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alert_status")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("status")


class AlertTypeSensor(_AlertSensor):
    """The most urgent threat type; every type and threat is in the attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [TYPE_NONE, *TYPE_PRIORITY]
    _attr_translation_key = "alert_type"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alert_type")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("type")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "types": data.get("types", []),
            "threats": data.get("threats", []),
            "threat_details": data.get("threat_details", []),
        }


class AlertSinceSensor(_AlertSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "alert_since"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alert_since")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.get("since")


class LastUpdateSensor(NebosvitAlertEntity, SensorEntity):
    """When the server last confirmed the alert data fresh: shows at a glance
    whether what Home Assistant knows is current."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_update"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_update")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.get("updated_at")

    @property
    def extra_state_attributes(self) -> dict:
        return {"live_socket": self.coordinator.live, "version": self.coordinator.data.get("version")}


class _PowerSensor(TickingEntity, SensorEntity):
    @property
    def _timeline(self) -> dict:
        return self.coordinator.data["schedule"]

    def _source_attributes(self, day: dict | None) -> dict:
        day = day or {}
        return {
            "source_name": day.get("sourceName"),
            "source_url": day.get("sourceUrl"),
            "updated_at": day.get("updatedAt"),
            "fetched_at": day.get("fetchedAt"),
            "stale": bool(day.get("stale")),
            "third_party": bool(day.get("thirdParty")),
            "note": day.get("note"),
        }

    def _day(self, offset: int) -> dict | None:
        day = kyiv_date(dt_util.now()) + timedelta(days=offset)
        return self._timeline["days"].get(day.isoformat())

    def _intervals(self, offset: int) -> list[dict]:
        day = kyiv_date(dt_util.now()) + timedelta(days=offset)
        return [
            {"from": s.isoformat(), "to": e.isoformat(), "type": t}
            for s, e, t in day_intervals(self._timeline, day)
        ]


class PowerStateSensor(_PowerSensor):
    """Light according to the published schedule (not a live measurement)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [POWER_ON, POWER_OFF, POWER_MAYBE_OFF, POWER_UNKNOWN]
    _attr_translation_key = "power_state"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_state")

    @property
    def native_value(self) -> str:
        return power_state_at(self._timeline, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict:
        area = self.coordinator.data["area"]
        return {
            "area": area.get("name"),
            "operator": area.get("operator"),
            "queue": self._config[CONF_POWER_QUEUE],
            "schedule_only": True,
            "intervals": [
                {"from": s.isoformat(), "to": e.isoformat(), "type": t}
                for s, e, t in self._timeline["intervals"]
            ],
            "intervals_today": self._intervals(0),
            "intervals_tomorrow": self._intervals(1),
            **self._source_attributes(self._day(0)),
            "source_url": self._day(0) and self._day(0).get("sourceUrl") or area.get("sourceUrl"),
        }


class PowerNextChangeSensor(_PowerSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "power_next_change"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_next_change")

    @property
    def native_value(self) -> datetime | None:
        return next_power_change(self._timeline, dt_util.now())


class PowerNextOffSensor(_PowerSensor):
    """When the light goes off by the schedule next; a possible outage is in the attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "power_next_off"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_next_off")

    @property
    def native_value(self) -> datetime | None:
        return next_transition_to(self._timeline, dt_util.now(), POWER_OFF)

    @property
    def extra_state_attributes(self) -> dict:
        maybe = next_transition_to(self._timeline, dt_util.now(), POWER_MAYBE_OFF)
        return {"next_maybe_off": maybe.isoformat() if maybe else None}


class PowerNextOnSensor(_PowerSensor):
    """When the light comes back by the schedule."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "power_next_on"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_next_on")

    @property
    def native_value(self) -> datetime | None:
        return next_transition_to(self._timeline, dt_util.now(), POWER_ON)


class PowerOffTodaySensor(_PowerSensor):
    """Minutes without light today by the schedule; unknown without a schedule."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "power_off_today"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_off_today")

    @property
    def native_value(self) -> int | None:
        return minutes_on_day(self._timeline, kyiv_date(dt_util.now()), POWER_OFF)

    @property
    def extra_state_attributes(self) -> dict:
        return {"maybe_off_minutes": minutes_on_day(self._timeline, kyiv_date(dt_util.now()), POWER_MAYBE_OFF)}


class ScheduleDaySensor(_PowerSensor):
    """Whether the schedule for today / tomorrow is published, and its slots."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = DAY_STATUSES

    def __init__(self, coordinator, entry: ConfigEntry, tomorrow: bool) -> None:
        key = "schedule_tomorrow" if tomorrow else "schedule_today"
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._offset = 1 if tomorrow else 0

    @property
    def native_value(self) -> str:
        return day_status(self._day(self._offset))

    @property
    def extra_state_attributes(self) -> dict:
        day = self._day(self._offset) or {}
        return {
            "date": day.get("date"),
            "intervals": self._intervals(self._offset),
            "image_url": day.get("imageUrl"),
            **self._source_attributes(day),
        }


def outage_attributes(row: dict) -> dict:
    return {
        "kind": row.get("kind"),
        "reason": row.get("reason"),
        "start": row.get("start"),
        "end": row.get("end"),
        "end_is_estimate": bool(row.get("endIsEstimate")),
        "street": row.get("street"),
        "houses": row.get("houses"),
        "match": row.get("match"),
        "cancelled": row.get("state") == "CANCELLED",
    }


class NextOutageSensor(TickingEntity, SensorEntity):
    """Start of the next planned or emergency outage at my address."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_outage"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_outage")

    def _rows(self) -> list[dict]:
        return matched_outages(
            self.coordinator.data.get("outages") or [],
            self._config.get(CONF_STREET),
            self._config.get(CONF_HOUSE),
            dt_util.utcnow(),
        )

    def _upcoming(self) -> list[dict]:
        now = dt_util.utcnow()
        return [r for r in self._rows() if r.get("state") != "CANCELLED" and not outage_is_on(r, now)]

    @property
    def native_value(self) -> datetime | None:
        upcoming = self._upcoming()
        return dt_util.parse_datetime(upcoming[0]["start"]) if upcoming else None

    @property
    def extra_state_attributes(self) -> dict:
        doc = self.coordinator.data
        upcoming = self._upcoming()
        coverage = doc.get("coverage") or {}
        return {
            **(outage_attributes(upcoming[0]) if upcoming else {}),
            "upcoming": [outage_attributes(r) for r in self._rows()[:10]],
            "settlement": self._config.get(CONF_SETTLEMENT_NAME),
            "planned_published": bool(coverage.get("planned")),
            "emergency_published": bool(coverage.get("emergency")),
            "coverage_note": coverage.get("note"),
            "sources": doc.get("sources") or [],
        }
