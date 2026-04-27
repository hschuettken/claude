"""Unit tests for WeeklyPlanBuilder (FR #2117).

Run with:
    cd /home/hesch/dev/projects/claude
    python -m pytest services/ev-forecast/test_weekly_plan.py -v
"""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

# Allow importing service-local modules without installing the package
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))

from trips import Trip


def _make_trip(
    trip_date: date,
    destination: str = "Münster",
    round_trip_km: float = 120.0,
    departure_time: time | None = None,
) -> Trip:
    """Helper: create a minimal Trip fixture."""
    return Trip(
        date=trip_date,
        person="Henning",
        destination=destination,
        distance_km=round_trip_km / 2,
        round_trip_km=round_trip_km,
        energy_kwh=round_trip_km * 22 / 100,
        departure_time=departure_time or time(8, 0),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_weekly_plan_7_days_length():
    """WeeklyPlanBuilder always returns exactly 7 EVDailyPlan entries."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)
    plan = builder.build(
        trips=[],
        current_soc_pct=70.0,
        battery_capacity_kwh=76.0,
        consumption_kwh_per_100km=22.0,
        pv_forecast_by_date={},
        today=today,
        timestamp="2026-04-12T10:00:00",
    )
    assert len(plan.days) == 7, f"Expected 7 days, got {len(plan.days)}"
    # Verify date sequence
    for i, day in enumerate(plan.days):
        expected = date(2026, 4, 12 + i).isoformat()
        assert day.date == expected, f"Day {i}: expected {expected}, got {day.date}"


def test_weekly_plan_pv_only_day():
    """A day where PV covers the whole deficit → charge_source_recommendation == 'pv_only'.

    Updated for SoC-aware builder (S2): start at 30% SoC so a real deficit
    exists, then provide ample PV.
    """
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)

    # Trip needs ~27.72 kWh; required = 27.72 + 19 (min_arrival) = 46.72 kWh.
    # current = 30% × 76 = 22.8 kWh; deficit ≈ 24 kWh.
    trip = _make_trip(today, round_trip_km=120.0)

    # PV covers more than enough of the deficit.
    pv_by_date = {today.isoformat(): 30.0}

    plan = builder.build(
        trips=[trip],
        current_soc_pct=30.0,
        battery_capacity_kwh=76.0,
        consumption_kwh_per_100km=22.0,
        pv_forecast_by_date=pv_by_date,
        today=today,
        timestamp="2026-04-12T10:00:00",
    )
    day0 = plan.days[0]
    assert day0.charge_source_recommendation == "pv_only", (
        f"Expected 'pv_only', got '{day0.charge_source_recommendation}' "
        f"(energy_needed={day0.energy_needed_kwh}, pv={day0.pv_expected_kwh})"
    )
    assert day0.grid_needed_kwh == 0.0


def test_weekly_plan_grid_required():
    """No PV and SoC below buffer → charge_source_recommendation == 'grid_required'."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)
    trip = _make_trip(today, round_trip_km=80.0)

    plan = builder.build(
        trips=[trip],
        current_soc_pct=30.0,  # 22.8 kWh; need 18.5 + 19 = 37.5 → deficit ≈ 15
        battery_capacity_kwh=76.0,
        consumption_kwh_per_100km=22.0,
        pv_forecast_by_date={},  # no PV forecast
        today=today,
        timestamp="2026-04-12T10:00:00",
    )
    day0 = plan.days[0]
    assert day0.charge_source_recommendation == "grid_required", (
        f"Expected 'grid_required', got '{day0.charge_source_recommendation}'"
    )
    assert day0.pv_expected_kwh == 0.0
    assert day0.grid_needed_kwh > 0.0


def test_weekly_plan_pv_plus_grid():
    """PV covers some but not all of the SoC-aware deficit → 'pv_plus_grid'."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)

    # 30% SoC + 120 km trip → deficit ≈ 24 kWh; PV ≈ 12 kWh → grid ≈ 12 kWh.
    trip = _make_trip(today, round_trip_km=120.0)
    pv_by_date = {today.isoformat(): 12.0}

    plan = builder.build(
        trips=[trip],
        current_soc_pct=30.0,
        battery_capacity_kwh=76.0,
        consumption_kwh_per_100km=22.0,
        pv_forecast_by_date=pv_by_date,
        today=today,
        timestamp="2026-04-12T10:00:00",
    )
    day0 = plan.days[0]
    assert day0.charge_source_recommendation == "pv_plus_grid", (
        f"Expected 'pv_plus_grid', got '{day0.charge_source_recommendation}'"
    )
    assert day0.pv_expected_kwh > 0.0
    assert day0.grid_needed_kwh > 0.0
    # In the new model, pv_used + grid_needed == deficit (not == energy_needed).
    # Sanity-check both numbers are sensible.
    assert day0.grid_needed_kwh < day0.energy_needed_kwh
