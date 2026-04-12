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
    """A day where PV covers all energy needs → charge_source_recommendation == 'pv_only'."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)

    # Trip needs ~26.4 kWh (120 km × 22 kWh/100km × 1.05 buffer)
    trip = _make_trip(today, round_trip_km=120.0)
    energy_needed = 120.0 * 22.0 / 100.0 * 1.05  # ~27.72

    # PV provides more than enough
    pv_by_date = {today.isoformat(): energy_needed + 5.0}

    plan = builder.build(
        trips=[trip],
        current_soc_pct=80.0,
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
    """No PV and a trip needed → charge_source_recommendation == 'grid_required'."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)
    trip = _make_trip(today, round_trip_km=80.0)

    plan = builder.build(
        trips=[trip],
        current_soc_pct=60.0,
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
    """PV covers some but not all energy → charge_source_recommendation == 'pv_plus_grid'."""
    from planner import WeeklyPlanBuilder

    builder = WeeklyPlanBuilder()
    today = date(2026, 4, 12)

    # Trip needs ~27.72 kWh (120 km × 22/100 × 1.05)
    trip = _make_trip(today, round_trip_km=120.0)
    energy_needed = 120.0 * 22.0 / 100.0 * 1.05

    # PV covers half
    pv_partial = energy_needed / 2.0
    pv_by_date = {today.isoformat(): pv_partial}

    plan = builder.build(
        trips=[trip],
        current_soc_pct=70.0,
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
    assert (
        abs(day0.grid_needed_kwh - (day0.energy_needed_kwh - day0.pv_expected_kwh))
        < 0.01
    )
