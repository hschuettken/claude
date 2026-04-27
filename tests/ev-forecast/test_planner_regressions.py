"""Regression tests for ChargingPlanner — pins specific bugs from journal review (S2 / FR #3059)."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from planner import ChargingPlanner
from trips import DayPlan, Trip
from vehicle import VehicleState


CONSUMPTION_KWH_PER_100KM = 22.0
NET_KWH = 76.0


def _commute_trip(d: date, km_round: float = 44.0) -> Trip:
    """Nicole's regular Lengerich commute — 22 km × 2."""
    energy = km_round * CONSUMPTION_KWH_PER_100KM / 100.0
    return Trip(
        date=d,
        person="Nicole",
        destination="Lengerich",
        distance_km=km_round / 2.0,
        round_trip_km=km_round,
        energy_kwh=energy,
        departure_time=time(7, 0),
        return_time=time(18, 0),
        is_commute=True,
        source="default_commute",
    )


def _vehicle(soc: float, plug: str = "connected") -> VehicleState:
    return VehicleState(
        soc_pct=soc,
        range_km=350.0,
        charging_state="not_charging",
        plug_state=plug,
        mileage_km=12345.0,
        active_account="single",
    )


def _planner() -> ChargingPlanner:
    ha = MagicMock()
    ha.get_state = AsyncMock(return_value={"state": "unknown"})
    return ChargingPlanner(ha=ha, net_capacity_kwh=NET_KWH)


@pytest.mark.asyncio
async def test_high_soc_only_commute_means_zero_charge():
    """At 90% SoC with only Nicole's commute tomorrow, plan must say 0 kWh charge.

    Pins the senseless-3-kWh bug: planner used to recommend charging even when
    current SoC trivially covered the demand.
    """
    planner = _planner()
    today = date(2026, 4, 28)  # Tuesday
    tomorrow = today + timedelta(days=1)

    day_plans = [
        DayPlan(date=today, trips=[]),
        DayPlan(date=tomorrow, trips=[_commute_trip(tomorrow)]),
    ]

    plan = await planner.generate_plan(_vehicle(soc=90.0), day_plans)

    # 90% SoC ≈ 68.4 kWh; commute is 9.7 kWh; min-arrival buffer ≪ surplus.
    assert plan.days[1].energy_to_charge_kwh == 0.0, (
        f"Expected 0 kWh charge, got {plan.days[1].energy_to_charge_kwh:.2f} kWh. "
        f"Reason: {plan.days[1].reason!r}"
    )
    assert plan.days[1].charge_mode == "PV Surplus"
    assert plan.days[1].urgency == "none"


@pytest.mark.asyncio
async def test_low_soc_with_commute_needs_significant_charge():
    """Sanity: at 5% SoC with commute, deficit must be substantial.

    NB: 0% SoC is treated as "missing" by the planner and falls back to
    `default_assumed_soc_pct=50.0`, which would mask the deficit. Use 5% for
    a meaningful low-SoC signal.
    """
    planner = _planner()
    tomorrow = date(2026, 4, 28)
    day_plans = [
        DayPlan(date=tomorrow - timedelta(days=1), trips=[]),
        DayPlan(date=tomorrow, trips=[_commute_trip(tomorrow)]),
    ]

    plan = await planner.generate_plan(_vehicle(soc=5.0), day_plans)

    # 5% SoC ≈ 3.8 kWh; commute is 9.7 kWh; min-arrival buffer pushes deficit > 15 kWh.
    assert plan.days[1].energy_to_charge_kwh > 15.0, (
        f"Expected > 15 kWh from 5% SoC, got "
        f"{plan.days[1].energy_to_charge_kwh:.2f} kWh"
    )


@pytest.mark.asyncio
async def test_no_trips_means_zero_charge_regardless_of_soc():
    """No trips = no demand, period."""
    planner = _planner()
    today = date(2026, 4, 28)
    day_plans = [
        DayPlan(date=today, trips=[]),
        DayPlan(date=today + timedelta(days=1), trips=[]),
    ]

    plan = await planner.generate_plan(_vehicle(soc=30.0), day_plans)

    for d in plan.days:
        assert d.energy_to_charge_kwh == 0.0, (
            f"Expected 0 kWh on a no-trip day at any SoC, got "
            f"{d.energy_to_charge_kwh:.2f} on {d.date}"
        )
