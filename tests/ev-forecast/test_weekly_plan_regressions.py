"""Regression tests for WeeklyPlanBuilder — pins SoC-aware behavior (S2 / FR #3059)."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from planner import WeeklyPlanBuilder
from trips import Trip


CONSUMPTION_KWH_PER_100KM = 22.0
NET_KWH = 76.0


def _commute_trip(d: date, km_round: float = 44.0) -> Trip:
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


def test_high_soc_commute_only_does_not_recommend_grid():
    """At 90% SoC with only commute tomorrow, weekly plan must NOT request grid charge.

    Pins the senseless-3-kWh bug: WeeklyPlanBuilder used to compute
    `grid_needed = energy_needed - pv_expected`, ignoring current SoC entirely.
    """
    today = date(2026, 4, 28)
    tomorrow = today + timedelta(days=1)
    plan = WeeklyPlanBuilder().build(
        trips=[_commute_trip(tomorrow)],
        current_soc_pct=90.0,
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={tomorrow.isoformat(): 0.0},  # no PV forecast for tomorrow
        today=today,
    )
    tomorrow_plan = next(d for d in plan.days if d.date == tomorrow.isoformat())
    # 90% SoC = 68 kWh; commute = 9.7 kWh; 25% min-arrival buffer = 19 kWh.
    # 68 - 9.7 = 58 kWh remaining ≫ 19 kWh buffer → grid_needed must be 0.
    assert tomorrow_plan.grid_needed_kwh == 0.0, (
        f"Expected grid_needed=0 at 90% SoC + commute only, got "
        f"{tomorrow_plan.grid_needed_kwh:.2f} kWh"
    )
    assert tomorrow_plan.charge_source_recommendation == "no_charge_needed"


def test_low_soc_commute_grid_requested():
    """At 10% SoC + commute + no PV, total grid demand is substantial.

    The running SoC update tops up across days, so tomorrow's *delta* is
    only the trip drain. What we care about is that the WEEK's grid total
    reflects the gap between starting SoC and min_arrival + commute drain.
    """
    today = date(2026, 4, 28)
    tomorrow = today + timedelta(days=1)
    plan = WeeklyPlanBuilder().build(
        trips=[_commute_trip(tomorrow)],
        current_soc_pct=10.0,
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={tomorrow.isoformat(): 0.0},
        today=today,
    )
    total_grid = sum(d.grid_needed_kwh for d in plan.days)
    # 10% SoC = 7.6 kWh; min_arrival 19 kWh; commute 9.7 kWh.
    # Total grid ≈ (19-7.6) + 9.7 = 21 kWh across today + tomorrow.
    assert total_grid > 15.0, (
        f"Expected total weekly grid demand > 15 kWh at 10% SoC + commute, got "
        f"{total_grid:.2f} kWh ({[d.grid_needed_kwh for d in plan.days]})"
    )
    tomorrow_plan = next(d for d in plan.days if d.date == tomorrow.isoformat())
    assert tomorrow_plan.charge_source_recommendation == "grid_required"


def test_low_soc_commute_with_pv_no_grid():
    """At 10% SoC + commute + abundant PV, no grid needed."""
    today = date(2026, 4, 28)
    tomorrow = today + timedelta(days=1)
    plan = WeeklyPlanBuilder().build(
        trips=[_commute_trip(tomorrow)],
        current_soc_pct=10.0,
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={tomorrow.isoformat(): 30.0},  # plenty of PV
        today=today,
    )
    tomorrow_plan = next(d for d in plan.days if d.date == tomorrow.isoformat())
    # PV (30 kWh) > deficit (~21 kWh) → grid 0, source = pv_only.
    assert tomorrow_plan.grid_needed_kwh == 0.0
    assert tomorrow_plan.charge_source_recommendation == "pv_only"


def test_min_arrival_soc_pct_override_changes_deficit():
    """Higher min_arrival_soc_pct floor → more buffer → larger deficit at low SoC.

    Confirms the WeeklyPlanBuilder honors the min_arrival_soc_pct parameter
    that ev-forecast threads through from the HA helper
    `input_number.ev_ready_by_min_soc_pct`.
    """
    today = date(2026, 4, 28)
    tomorrow = today + timedelta(days=1)
    args = dict(
        trips=[_commute_trip(tomorrow)],
        current_soc_pct=30.0,  # 22.8 kWh
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={tomorrow.isoformat(): 0.0},
        today=today,
    )

    plan_25 = WeeklyPlanBuilder().build(**args, min_arrival_soc_pct=25.0)
    plan_40 = WeeklyPlanBuilder().build(**args, min_arrival_soc_pct=40.0)

    total_25 = sum(d.grid_needed_kwh for d in plan_25.days)
    total_40 = sum(d.grid_needed_kwh for d in plan_40.days)

    # 40% buffer = 30.4 kWh; 25% buffer = 19 kWh; trip = 9.7 kWh.
    # At 22.8 kWh starting, the 40% scenario must demand more grid.
    assert total_40 > total_25, (
        f"Expected higher min_arrival to increase grid demand. "
        f"25%: {total_25:.2f} kWh, 40%: {total_40:.2f} kWh"
    )
    # Sanity: gap should be ~ (40-25)% × 76 = 11.4 kWh
    assert (total_40 - total_25) > 8.0


def test_min_arrival_soc_pct_default_is_25():
    """Default (no override) uses WeeklyPlanBuilder.MIN_ARRIVAL_SOC_PCT (25%)."""
    today = date(2026, 4, 28)
    tomorrow = today + timedelta(days=1)
    args = dict(
        trips=[_commute_trip(tomorrow)],
        current_soc_pct=30.0,
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={tomorrow.isoformat(): 0.0},
        today=today,
    )
    default_plan = WeeklyPlanBuilder().build(**args)
    explicit_25 = WeeklyPlanBuilder().build(**args, min_arrival_soc_pct=25.0)

    default_total = sum(d.grid_needed_kwh for d in default_plan.days)
    explicit_total = sum(d.grid_needed_kwh for d in explicit_25.days)
    assert default_total == pytest.approx(explicit_total, abs=0.01), (
        "Default min_arrival_soc_pct should equal MIN_ARRIVAL_SOC_PCT class constant"
    )


def test_no_trips_no_charge():
    today = date(2026, 4, 28)
    plan = WeeklyPlanBuilder().build(
        trips=[],
        current_soc_pct=50.0,
        battery_capacity_kwh=NET_KWH,
        consumption_kwh_per_100km=CONSUMPTION_KWH_PER_100KM,
        pv_forecast_by_date={},
        today=today,
    )
    for day in plan.days:
        assert day.grid_needed_kwh == 0.0
        assert day.charge_source_recommendation == "no_charge_needed"
