"""Tests for the greedy charge-window scheduler (S2 / FR #3059)."""

from datetime import datetime, timedelta, timezone

import pytest

from scheduler import HourlyPV, schedule_charge_windows


NOW = datetime(2026, 4, 28, 8, 0, 0, tzinfo=timezone.utc)


def _flat_pv(
    start: datetime, hours: int, kwh_per_hour: float, conf: float = 0.2
) -> list[HourlyPV]:
    """Helper: list of HourlyPV with constant kWh and ±conf range."""
    return [
        HourlyPV(
            time=start + timedelta(hours=i),
            kwh=kwh_per_hour,
            conf_low=kwh_per_hour - conf,
            conf_high=kwh_per_hour + conf,
        )
        for i in range(hours)
    ]


def test_no_demand_returns_empty():
    pv = _flat_pv(NOW, 24, 2.0)
    r = schedule_charge_windows(
        pv, demand_kwh=0.0, deadline=NOW + timedelta(hours=12), now=NOW
    )
    assert r.windows == []
    assert r.reason == "no demand"


def test_pv_sufficient_no_grid():
    """3 kWh × 24h available; need 10 kWh by 12h → all PV, no grid."""
    pv = _flat_pv(NOW, 24, 3.0)
    r = schedule_charge_windows(
        pv, demand_kwh=10.0, deadline=NOW + timedelta(hours=12), now=NOW
    )
    assert r.grid_kwh == 0.0
    assert r.pv_kwh == pytest.approx(10.0, abs=0.1)


def test_pv_insufficient_grid_fills_latest_first():
    """1 kWh × 12h available PV; need 16 kWh; grid must defer to latest hours."""
    pv = _flat_pv(NOW, 12, 1.0)
    deadline = NOW + timedelta(hours=12)
    r = schedule_charge_windows(pv, demand_kwh=16.0, deadline=deadline, now=NOW)
    # conf_low = 0.8 → 12 × 0.8 = 9.6 kWh PV used
    assert r.pv_kwh == pytest.approx(9.6, abs=0.5)
    assert r.grid_kwh > 0
    grid_windows = [w for w in r.windows if w.source == "grid"]
    pv_windows = [w for w in r.windows if w.source == "pv"]
    # Grid windows should not be earlier than the latest PV window
    last_pv_start = max(w.start for w in pv_windows)
    assert any(w.start >= last_pv_start for w in grid_windows)


def test_no_deadline_pv_only_mode():
    """24 kWh PV total; need 30 kWh; no deadline → defer remainder."""
    pv = _flat_pv(NOW, 24, 1.0)
    r = schedule_charge_windows(pv, demand_kwh=30.0, deadline=None, now=NOW)
    assert r.grid_kwh == 0.0
    assert r.deferred_kwh > 0
    assert "deferring" in r.reason.lower()


def test_wallbox_cap_respected():
    """Huge PV but wallbox capped at 11 kW/h."""
    pv = _flat_pv(NOW, 4, 20.0)
    r = schedule_charge_windows(
        pv,
        demand_kwh=80.0,
        deadline=NOW + timedelta(hours=4),
        now=NOW,
        wallbox_max_kwh_per_hour=11.0,
    )
    for w in r.windows:
        assert w.kwh <= 11.0


def test_confidence_low_used():
    """Wide confidence band → use conf_low, not central kWh."""
    pv = [
        HourlyPV(time=NOW, kwh=5.0, conf_low=2.0, conf_high=8.0),
    ]
    r = schedule_charge_windows(
        pv, demand_kwh=10.0, deadline=NOW + timedelta(hours=1), now=NOW
    )
    # Should only use 2 kWh from PV (conf_low), rest from grid.
    assert r.pv_kwh == pytest.approx(2.0, abs=0.1)
    assert r.grid_kwh == pytest.approx(8.0, abs=0.5)
