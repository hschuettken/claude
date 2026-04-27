"""Greedy charge-window scheduler (S2 / FR #3059).

Given an hour-by-hour PV forecast and a need-by-deadline, allocate kWh
to hours preferring PV (free + green) over grid (paid). When PV
forecast confidence is wide, treats the hour's available PV as
`conf_low` (conservative).

Replaces the older "fill the deficit, pick mode by urgency tier"
approach with a real schedule of charge windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal


@dataclass
class HourlyPV:
    """One hour of PV forecast input to the scheduler."""

    time: datetime  # UTC, top-of-hour
    kwh: float
    conf_low: float
    conf_high: float


@dataclass
class ChargeWindow:
    """One hour of allocated charging."""

    start: datetime  # UTC
    end: datetime  # UTC (start + 1h)
    kwh: float
    source: Literal["pv", "grid"]


@dataclass
class ScheduleResult:
    windows: list[ChargeWindow] = field(default_factory=list)
    total_kwh: float = 0.0
    pv_kwh: float = 0.0
    grid_kwh: float = 0.0
    deferred_kwh: float = 0.0  # PV-only mode + insufficient PV → wait for more
    reason: str = ""


def schedule_charge_windows(
    hourly_pv: list[HourlyPV],
    *,
    demand_kwh: float,
    deadline: datetime | None,  # UTC, or None for "no upcoming trip"
    wallbox_max_kwh_per_hour: float = 11.0,
    now: datetime | None = None,
) -> ScheduleResult:
    """Greedy schedule: allocate `demand_kwh` to hours, preferring PV.

    Algorithm:
      1. needed = demand_kwh
      2. Filter slots to [now..deadline) (or full list if no deadline)
      3. PV pass — earliest first; allocate min(conf_low, wallbox cap, needed) per slot
      4. If still needed AND deadline given: grid pass latest-first
      5. If still needed AND no deadline: defer remainder

    Confidence-aware: uses `conf_low` as the available PV (conservative).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = ScheduleResult()
    if demand_kwh <= 0:
        result.reason = "no demand"
        return result

    needed = demand_kwh

    # Round `now` down to top-of-hour for comparison with slot timestamps.
    now_floor = now.replace(minute=0, second=0, microsecond=0)
    relevant = [s for s in hourly_pv if s.time >= now_floor]
    if deadline is not None:
        relevant = [s for s in relevant if s.time < deadline]

    # PV pass — earliest first
    for slot in sorted(relevant, key=lambda s: s.time):
        if needed <= 0:
            break
        pv_avail = max(0.0, slot.conf_low)
        allocate = min(pv_avail, wallbox_max_kwh_per_hour, needed)
        if allocate > 0.001:
            result.windows.append(
                ChargeWindow(
                    start=slot.time,
                    end=slot.time + timedelta(hours=1),
                    kwh=round(allocate, 3),
                    source="pv",
                )
            )
            needed -= allocate
            result.pv_kwh += allocate

    # Grid pass — only if deadline exists and PV insufficient.
    # Latest-first defers grid, leaving PV room earlier in the window.
    if needed > 0.001 and deadline is not None:
        for slot in sorted(relevant, key=lambda s: s.time, reverse=True):
            if needed <= 0:
                break
            already_allocated = sum(
                w.kwh for w in result.windows if w.start == slot.time
            )
            grid_room = wallbox_max_kwh_per_hour - already_allocated
            allocate = min(grid_room, needed)
            if allocate > 0.001:
                result.windows.append(
                    ChargeWindow(
                        start=slot.time,
                        end=slot.time + timedelta(hours=1),
                        kwh=round(allocate, 3),
                        source="grid",
                    )
                )
                needed -= allocate
                result.grid_kwh += allocate

    # PV-only deferred case
    if needed > 0.001 and deadline is None:
        result.deferred_kwh = round(needed, 3)
        result.reason = (
            f"PV forecast insufficient ({result.pv_kwh:.1f} kWh of "
            f"{demand_kwh:.1f} kWh need); deferring rest until deadline known"
        )
    elif needed > 0.001:
        result.reason = f"Insufficient capacity: short by {needed:.1f} kWh by deadline"
    else:
        if result.grid_kwh > 0:
            result.reason = (
                f"PV {result.pv_kwh:.1f} kWh + grid {result.grid_kwh:.1f} kWh "
                f"= {demand_kwh:.1f} kWh by deadline"
            )
        else:
            result.reason = f"PV-only: {result.pv_kwh:.1f} kWh from forecast"

    result.windows.sort(key=lambda w: w.start)
    result.total_kwh = round(result.pv_kwh + result.grid_kwh, 3)
    result.pv_kwh = round(result.pv_kwh, 3)
    result.grid_kwh = round(result.grid_kwh, 3)
    return result
