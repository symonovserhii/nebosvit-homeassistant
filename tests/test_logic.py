"""Tests of the integration's pure logic, without Home Assistant.

Run from the repository root: python3 -I -m unittest discover -s tests -p "test_*.py"
address_cases.json is shared with the Nebosvit apps and server.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_DIR = HERE.parent / "custom_components" / "nebosvit"

# The package's __init__ needs Home Assistant; register the package without
# running it, so its pure modules import with their relative imports.
_pkg = types.ModuleType("nebosvit_pure")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["nebosvit_pure"] = _pkg
addressing = importlib.import_module("nebosvit_pure.addressing")
timeline = importlib.import_module("nebosvit_pure.timeline")
regions = importlib.import_module("nebosvit_pure.regions")

CASES = json.loads((HERE / "address_cases.json").read_text())

MATCH_NAMES = {"EXACT": addressing.MATCH_EXACT, "STREET": addressing.MATCH_STREET,
               "POSSIBLE": addressing.MATCH_POSSIBLE, "": None}


class SharedAddressCases(unittest.TestCase):
    def test_normalize_name(self):
        for c in CASES["normalizeName"]:
            self.assertEqual(addressing.normalize_name(c["in"]), c["out"], c["in"])

    def test_same_street(self):
        for c in CASES["sameStreet"]:
            self.assertEqual(addressing.same_street(c["a"], c["b"]), c["same"], c)

    def test_normalize_house(self):
        for c in CASES["normalizeHouse"]:
            self.assertEqual(addressing.normalize_house(c["in"]), c["out"], c["in"])

    def test_match(self):
        for c in CASES["match"]:
            got = addressing.match(c["street"], c["tokens"], c["housesParsed"], c["wholeStreet"],
                                   c["userStreet"], c["userHouse"])
            self.assertEqual(got, MATCH_NAMES[c["expect"]], c)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


AREA = {
    "id": "kyiv-city",
    "days": [
        {"date": "2026-10-28", "status": "APPLIES", "sourceName": "YASNO",
         "queues": {"1.1": [{"from": "08:00", "to": "10:00", "type": "OFF"},
                            {"from": "18:00", "to": "20:00", "type": "STRANGE"}],
                    "1.2": []}},
        {"date": "2026-10-29", "status": "WAITING", "queues": None},
    ],
}


class Schedule(unittest.TestCase):
    def setUp(self):
        self.t = timeline.build_timeline(AREA, "1.1")

    def test_states(self):
        # Kyiv is UTC+2 on 2026-10-28.
        self.assertEqual(timeline.power_state_at(self.t, utc(2026, 10, 28, 5, 0)), "on")
        self.assertEqual(timeline.power_state_at(self.t, utc(2026, 10, 28, 6, 30)), "off")
        self.assertEqual(timeline.power_state_at(self.t, utc(2026, 10, 28, 16, 30)), "maybe_off",
                         "an unknown slot type counts as maybe off")
        self.assertEqual(timeline.power_state_at(self.t, utc(2026, 10, 29, 6, 0)), "unknown",
                         "a waiting day is not power on")

    def test_transitions(self):
        now = utc(2026, 10, 28, 5, 0)
        self.assertEqual(timeline.next_transition_to(self.t, now, "off"), utc(2026, 10, 28, 6, 0))
        self.assertEqual(timeline.next_transition_to(self.t, now, "on"), utc(2026, 10, 28, 8, 0))
        self.assertEqual(timeline.next_power_change(self.t, now), utc(2026, 10, 28, 6, 0))
        # After the last slot the published data ends: no change, no "on".
        late = utc(2026, 10, 28, 19, 0)
        self.assertIsNone(timeline.next_transition_to(self.t, late, "off"))

    def test_minutes(self):
        self.assertEqual(timeline.minutes_on_day(self.t, date(2026, 10, 28), "off"), 120)
        self.assertEqual(timeline.minutes_on_day(self.t, date(2026, 10, 28), "maybe_off"), 120)
        self.assertIsNone(timeline.minutes_on_day(self.t, date(2026, 10, 29), "off"))

    def test_queue_without_outages_is_on(self):
        t = timeline.build_timeline(AREA, "1.2")
        self.assertEqual(timeline.power_state_at(t, utc(2026, 10, 28, 12, 0)), "on")
        self.assertEqual(timeline.minutes_on_day(t, date(2026, 10, 28), "off"), 0)

    def test_undescribed_queue_is_unknown(self):
        t = timeline.build_timeline(AREA, "6.2")
        self.assertEqual(timeline.power_state_at(t, utc(2026, 10, 28, 12, 0)), "unknown")

    def test_day_status(self):
        self.assertEqual(timeline.day_status({"status": "APPLIES"}), "applies")
        self.assertEqual(timeline.day_status({"status": "SOMETHING"}), "no_data")
        self.assertEqual(timeline.day_status(None), "no_data")


OUTAGES = [
    {"id": "a", "kind": "EMERGENCY", "start": "2026-10-28T07:00:00Z", "end": None,
     "street": "вул. Садова", "houseTokens": ["10", "12"], "housesParsed": True, "reason": "Аварія"},
    {"id": "b", "kind": "PLANNED", "start": "2026-10-29T06:00:00Z", "end": "2026-10-29T14:00:00Z",
     "street": "Садова", "houseTokens": ["1-20"], "housesParsed": True},
    {"id": "c", "kind": "PLANNED", "start": "2026-10-27T06:00:00Z", "end": "2026-10-27T14:00:00Z",
     "street": "Садова", "houseTokens": ["10"], "housesParsed": True},
    {"id": "d", "kind": "WHATEVER", "start": "2026-10-30T06:00:00Z", "end": "2026-10-30T08:00:00Z",
     "street": "Лісова", "houseTokens": ["10"], "housesParsed": True},
    {"id": "e", "kind": "PLANNED", "state": "CANCELLED", "start": "2026-10-28T06:00:00Z",
     "end": "2026-10-28T20:00:00Z", "street": "Садова", "houseTokens": ["10"], "housesParsed": True},
]


class Outages(unittest.TestCase):
    def test_matched(self):
        now = utc(2026, 10, 28, 9, 0)
        rows = timeline.matched_outages(OUTAGES, "Садова", "10", now)
        self.assertEqual([r["id"] for r in rows], ["a", "e", "b"], "on now first; finished and other streets left out")
        self.assertTrue(timeline.outage_is_on(rows[0], now))
        self.assertFalse(timeline.outage_is_on(rows[1], now), "a cancelled outage is never on")
        self.assertEqual(rows[2]["match"], addressing.MATCH_EXACT, "10 is in the range 1-20")

    def test_unknown_kind_is_emergency(self):
        rows = timeline.matched_outages(OUTAGES, "Лісова", "10", utc(2026, 10, 28, 9, 0))
        self.assertEqual(rows[0]["kind"], "EMERGENCY")

    def test_settlement_only(self):
        rows = timeline.matched_outages(OUTAGES, "", "", utc(2026, 10, 28, 9, 0))
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["match"] == addressing.MATCH_STREET for r in rows))


if __name__ == "__main__":
    unittest.main()


class AlertScope(unittest.TestCase):
    """Kropyvnytska hromada (761) in raion 81 of Kirovohrad oblast (15)."""

    def test_own_place_raion_and_oblast(self):
        for alert in ({"regionId": "761", "oblastId": "15"}, {"regionId": "81", "oblastId": "15"},
                      {"regionId": "15", "oblastId": "15"}):
            self.assertTrue(regions.alert_matches("761", alert), alert)

    def test_elsewhere_in_oblast_only_with_whole_oblast(self):
        other = next(rid for rid, row in regions._load().items()
                     if row["rank"] == "2" and row["parent"] == "15" and rid != "81")
        alert = {"regionId": other, "oblastId": "15"}
        self.assertFalse(regions.alert_matches("761", alert))
        self.assertTrue(regions.alert_matches("761", alert, whole_oblast=True))
        self.assertFalse(regions.alert_matches("761", {"regionId": "22", "oblastId": "22"}, whole_oblast=True))
        self.assertEqual(regions.oblast_of("761"), "15")
