"""Outage schedule (GPV) as a timeline for one queue, and outages by address.

Rules from docs/api-contract.md: power is «on by the schedule» only on an
APPLIES day whose queue the source described; an unknown slot type counts as
MAYBE_OFF; an unknown day status as NO_DATA. No Home Assistant imports, so
the tests can load it without one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .addressing import match as match_address

KYIV = ZoneInfo("Europe/Kyiv")

POWER_ON = "on"
POWER_OFF = "off"
POWER_MAYBE_OFF = "maybe_off"
POWER_UNKNOWN = "unknown"

DAY_STATUSES = ["applies", "not_applied", "waiting", "no_data", "source_error"]


def _hhmm(day: str, hhmm: str) -> datetime:
    """Kyiv wall-clock time as an absolute UTC moment (safe across DST changes)."""
    hours, minutes = (int(x) for x in hhmm.split(":"))
    wall = datetime.fromisoformat(day) + timedelta(hours=hours, minutes=minutes)
    return wall.replace(tzinfo=KYIV).astimezone(timezone.utc)


def day_status(day: dict[str, Any] | None) -> str:
    status = str((day or {}).get("status", "")).lower()
    return status if status in DAY_STATUSES else "no_data"


def build_timeline(area: dict[str, Any], queue: str) -> dict[str, Any]:
    """The area's days for one queue: [(start, end, state)] and the covered days."""
    intervals: list[tuple[datetime, datetime, str]] = []
    known_days: list[tuple[datetime, datetime]] = []
    days: dict[str, dict[str, Any]] = {}
    for day in area.get("days", []):
        date_str = day.get("date")
        if not date_str:
            continue
        days[date_str] = day
        queues = day.get("queues")
        if day_status(day) != "applies" or not isinstance(queues, dict) or queue not in queues:
            continue
        known_days.append((_hhmm(date_str, "00:00"), _hhmm(date_str, "24:00")))
        for slot in queues[queue] or []:
            state = POWER_OFF if slot.get("type") == "OFF" else POWER_MAYBE_OFF
            intervals.append((_hhmm(date_str, slot["from"]), _hhmm(date_str, slot["to"]), state))
    intervals.sort()
    return {"intervals": intervals, "known_days": known_days, "days": days}


def power_state_at(timeline: dict[str, Any], now: datetime) -> str:
    now = now.astimezone(timezone.utc)
    for start, end, state in timeline["intervals"]:
        if start <= now < end:
            return state
    if any(start <= now < end for start, end in timeline["known_days"]):
        return POWER_ON
    return POWER_UNKNOWN


def _boundaries(timeline: dict[str, Any], now: datetime) -> list[datetime]:
    return sorted(
        {b for start, end, _ in timeline["intervals"] for b in (start, end) if b > now}
        | {b for start, end in timeline["known_days"] for b in (start, end) if b > now}
    )


def next_power_change(timeline: dict[str, Any], now: datetime) -> datetime | None:
    """The next moment the state differs from the current one."""
    now = now.astimezone(timezone.utc)
    current = power_state_at(timeline, now)
    if current == POWER_UNKNOWN:
        return None
    for boundary in _boundaries(timeline, now):
        following = power_state_at(timeline, boundary)
        # Running out of published data is not a change in the power itself.
        if following not in (current, POWER_UNKNOWN):
            return boundary
    return None


def next_transition_to(timeline: dict[str, Any], now: datetime, target: str) -> datetime | None:
    """The next moment the state becomes `target` (from another known state)."""
    now = now.astimezone(timezone.utc)
    previous = power_state_at(timeline, now)
    for boundary in _boundaries(timeline, now):
        state = power_state_at(timeline, boundary)
        if state == target and previous != target and previous != POWER_UNKNOWN:
            return boundary
        previous = state
    return None


def kyiv_date(now: datetime) -> date:
    return now.astimezone(KYIV).date()


def day_intervals(timeline: dict[str, Any], day: date) -> list[tuple[datetime, datetime, str]]:
    """Slots that fall on a Kyiv day, clipped to it."""
    start = datetime(day.year, day.month, day.day, tzinfo=KYIV).astimezone(timezone.utc)
    end = (datetime(day.year, day.month, day.day, tzinfo=KYIV) + timedelta(days=1)).astimezone(timezone.utc)
    return [
        (max(s, start), min(e, end), state)
        for s, e, state in timeline["intervals"]
        if s < end and e > start
    ]


def minutes_on_day(timeline: dict[str, Any], day: date, state: str) -> int | None:
    """Minutes in `state` on a Kyiv day; None when that day has no schedule."""
    if not any(s.astimezone(KYIV).date() == day for s, _ in timeline["known_days"]):
        return None
    total = sum((e - s for s, e, st in day_intervals(timeline, day) if st == state), timedelta())
    return int(total.total_seconds() // 60)


# Outages by address (/v1/outages/{area}/settlements/{id}).

def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def outage_is_on(outage: dict[str, Any], now: datetime) -> bool:
    """Started and not finished; an open end counts as on. Cancelled never."""
    if outage.get("state") == "CANCELLED":
        return False
    start, end = _parse(outage.get("start")), _parse(outage.get("end"))
    if start is None or start > now:
        return False
    return end is None or now < end


def matched_outages(
    outages: list[dict[str, Any]], street: str | None, house: str | None, now: datetime
) -> list[dict[str, Any]]:
    """Rows concerning the address, not finished, on now first, then by start.

    Each is the row plus `match` (exact / street / possible). Unknown kinds
    are treated as emergencies, never hidden.
    """
    now = now.astimezone(timezone.utc)
    out = []
    for o in outages:
        start = _parse(o.get("start"))
        if start is None:
            continue
        m = match_address(
            o.get("street", ""),
            o.get("houseTokens") or [],
            bool(o.get("housesParsed", True)),
            bool(o.get("wholeStreet", False)),
            street,
            house,
        )
        if m is None:
            continue
        end = _parse(o.get("end"))
        if end is not None and end <= now:
            continue
        row = dict(o)
        row["match"] = m
        if row.get("kind") not in ("PLANNED", "EMERGENCY"):
            row["kind"] = "EMERGENCY"
        out.append(row)
    out.sort(key=lambda r: (not outage_is_on(r, now), _parse(r["start"])))
    return out
