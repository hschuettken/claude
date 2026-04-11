"""Shared fixtures for all claude service tests."""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# WallboxState mock factory
# ---------------------------------------------------------------------------


def make_wallbox(
    vehicle_connected: bool = True,
    vehicle_charging: bool = True,
    current_power_w: float = 0.0,
    session_energy_kwh: float = 0.0,
) -> MagicMock:
    """Return a MagicMock that quacks like WallboxState."""
    wb = MagicMock()
    wb.vehicle_connected = vehicle_connected
    wb.vehicle_charging = vehicle_charging
    wb.current_power_w = current_power_w
    wb.session_energy_kwh = session_energy_kwh
    return wb


# ---------------------------------------------------------------------------
# ChargingContext factory (all fields with sensible defaults)
# ---------------------------------------------------------------------------


def make_ctx(**overrides) -> MagicMock:
    """
    Return a MagicMock that quacks like ChargingContext.

    All numeric defaults represent a mid-day, partial-PV scenario with a
    77 kWh EV battery at 50% SoC, target 80%, departure at 17:00.
    """

    # Base defaults
    defaults = dict(
        mode=None,  # caller must set
        wallbox=make_wallbox(),
        grid_power_w=0.0,
        pv_power_w=5000.0,
        battery_power_w=500.0,
        battery_soc_pct=60.0,
        pv_forecast_remaining_kwh=15.0,
        pv_forecast_tomorrow_kwh=20.0,
        house_power_w=800.0,
        battery_capacity_kwh=7.0,
        battery_target_eod_soc_pct=90.0,
        full_by_morning=False,
        departure_time=None,
        target_energy_kwh=30.0,
        session_energy_kwh=0.0,
        ev_soc_pct=50.0,
        ev_battery_capacity_kwh=77.0,
        ev_target_soc_pct=80.0,
        overnight_grid_kwh_charged=0.0,
        now=datetime(2024, 6, 15, 12, 0, 0),
        departure_passed=False,
        drain_pv_battery=False,
        drain_budget_kwh=0.0,
        drain_used_kwh=0.0,
    )
    defaults.update(overrides)

    ctx = MagicMock()
    for k, v in defaults.items():
        setattr(ctx, k, v)

    # Wire up computed properties
    def _energy_needed():
        if ctx.ev_soc_pct is not None and ctx.ev_battery_capacity_kwh > 0:
            delta = max(0.0, ctx.ev_target_soc_pct - ctx.ev_soc_pct)
            return delta / 100.0 * ctx.ev_battery_capacity_kwh
        return max(0.0, ctx.target_energy_kwh - ctx.session_energy_kwh)

    def _target_reached():
        if ctx.ev_soc_pct is not None:
            return ctx.ev_soc_pct >= ctx.ev_target_soc_pct
        return ctx.session_energy_kwh >= ctx.target_energy_kwh

    type(ctx).energy_needed_kwh = property(lambda self: _energy_needed())
    type(ctx).target_reached = property(lambda self: _target_reached())

    return ctx


@pytest.fixture
def wallbox():
    return make_wallbox()


@pytest.fixture
def default_ctx():
    """A default ChargingContext with PV surplus mode and vehicle connected."""
    from strategy import ChargeMode  # available after sys.path is patched

    return make_ctx(mode=ChargeMode.PV_SURPLUS)
