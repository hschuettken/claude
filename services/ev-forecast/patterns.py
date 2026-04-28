"""Pattern learning for ev-forecast (S6b, FR #3064).

Rolling medians for Nicole's commute departure/return times. Reads
presence events from the analytics bucket — falls back gracefully when
data is sparse.

Used weekly (Sunday 03:00) to update TripPredictor defaults so the
EV planner adapts to actual behavior over time.
"""

from __future__ import annotations

import statistics
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from shared.log import get_logger

if TYPE_CHECKING:
    from shared.influx_client import InfluxClient

logger = get_logger("ev_patterns")


def _median_time(times: list[time]) -> time:
    """Median of a list of `time` objects, ignoring sub-minute precision."""
    minutes = [t.hour * 60 + t.minute for t in times]
    median_min = int(statistics.median(minutes))
    return time(hour=median_min // 60, minute=median_min % 60)


def nicole_commute_pattern(
    influx_admin: "InfluxClient",
    *,
    days: int = 30,
    bucket: str = "analytics",
) -> dict:
    """Compute Nicole's median departure + return times from presence events.

    Returns dict with keys:
      - learned: bool (True only if both ≥5 samples)
      - median_departure: time | None
      - median_arrival: time | None
      - samples_dep: int
      - samples_arr: int
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> filter(fn: (r) => r._measurement == "presence_event")
  |> filter(fn: (r) => r.user == "nicole")
'''
    try:
        tables = influx_admin.query_raw(flux)
    except Exception as exc:
        logger.warning("pattern_query_failed", error=str(exc))
        return {
            "learned": False,
            "samples_dep": 0,
            "samples_arr": 0,
            "median_departure": None,
            "median_arrival": None,
        }

    departures: list[time] = []
    arrivals: list[time] = []
    for table in tables:
        for record in table.records:
            ts = record.get_time()
            if ts is None:
                continue
            kind = (record.values.get("event_kind") or "").lower()
            # Mon=0..Thu=3 — skip weekends
            if ts.weekday() >= 4:
                continue
            t_only = time(hour=ts.hour, minute=ts.minute)
            if kind == "left":
                departures.append(t_only)
            elif kind == "arrived":
                arrivals.append(t_only)

    if len(departures) < 5 or len(arrivals) < 5:
        return {
            "learned": False,
            "samples_dep": len(departures),
            "samples_arr": len(arrivals),
            "median_departure": None,
            "median_arrival": None,
        }

    return {
        "learned": True,
        "median_departure": _median_time(departures),
        "median_arrival": _median_time(arrivals),
        "samples_dep": len(departures),
        "samples_arr": len(arrivals),
    }
