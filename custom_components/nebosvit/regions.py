"""Region hierarchy (oblast > raion > hromada) shipped with the integration."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    path = Path(__file__).parent / "regions.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


def preload() -> None:
    """Read the CSV; call from an executor so the event loop never blocks."""
    _load()


def get_name(region_id: str) -> str:
    row = _load().get(region_id)
    return row["name"] if row else f"#{region_id}"


def oblasts() -> dict[str, str]:
    """Oblast id -> name, sorted by name."""
    rows = [(r["id"], r["name"]) for r in _load().values() if r["rank"] == "1"]
    return dict(sorted(rows, key=lambda x: x[1]))


def children_options(oblast_id: str) -> dict[str, str]:
    """The oblast itself plus every raion/hromada inside it, as id -> label."""
    regions = _load()
    parent_of = {rid: r["parent"] for rid, r in regions.items()}
    options: dict[str, str] = {oblast_id: f"★ {get_name(oblast_id)}"}
    raions = sorted(
        (rid for rid, r in regions.items() if r["parent"] == oblast_id),
        key=get_name,
    )
    for raion in raions:
        options[raion] = f"▸ {get_name(raion)}"
        hromadas = sorted(
            (rid for rid in regions if parent_of[rid] == raion), key=get_name
        )
        for hromada in hromadas:
            options[hromada] = f"      {get_name(hromada)}"
    return options


def ancestors(region_id: str) -> set[str]:
    """All parents of a region (not including the region itself)."""
    regions = _load()
    out: set[str] = set()
    current = regions.get(region_id)
    while current and current["parent"]:
        out.add(current["parent"])
        current = regions.get(current["parent"])
    return out


def alert_matches(region_id: str, alert: dict) -> bool:
    """True if an alert from the feed concerns the watched region.

    An alert counts when it covers the region (the region itself or any
    parent) or lies inside it (the watched region is its parent).
    """
    alert_region = str(alert.get("regionId", ""))
    if alert_region == region_id or alert_region in ancestors(region_id):
        return True
    if str(alert.get("oblastId", "")) == region_id:
        return True
    return region_id in ancestors(alert_region)
