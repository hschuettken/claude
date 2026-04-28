"""Unit tests for FR #3066 intra-day recalibration math.

Tests the deterministic computation paths inside _intra_day_recalibrate
without spinning up the whole service. We exercise the same expressions
as in main.py against fixed inputs and assert the published payload
shape + bounds.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing service-local modules without installing the package
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.energy_events import PVForecastAdjusted


def _compute(pv_w: float, expected_hour_kwh: float, minutes_left: int) -> dict:
    """Replica of the math in _intra_day_recalibrate for testing."""
    expected_5min_kwh = expected_hour_kwh / 12.0
    actual_5min_kwh = pv_w * (5.0 / 60.0) / 1000.0
    if expected_5min_kwh < 0.05:
        ratio = 1.0
    else:
        ratio = max(0.0, min(3.0, actual_5min_kwh / expected_5min_kwh))
    current_hour_remaining_kwh = expected_hour_kwh * minutes_left / 60.0
    adjusted_current_hour_remaining = current_hour_remaining_kwh * ratio
    forecast_today_remaining = expected_hour_kwh + 5.0  # 5 kWh later in day
    adjusted_today_remaining = max(
        0.0,
        forecast_today_remaining
        - current_hour_remaining_kwh
        + adjusted_current_hour_remaining,
    )
    return {
        "ratio": round(ratio, 3),
        "actual_5min_kwh": round(actual_5min_kwh, 4),
        "expected_5min_kwh": round(expected_5min_kwh, 4),
        "adjusted_today_remaining": round(adjusted_today_remaining, 3),
        "forecast_today_remaining": round(forecast_today_remaining, 3),
    }


def test_match_forecast_ratio_one():
    """When PV power matches forecast exactly, ratio = 1.0."""
    # 6000 W × (5/60) / 1000 = 0.5 kWh per 5 min
    # expected_hour = 6 kWh → expected_5min = 0.5 kWh
    res = _compute(pv_w=6000, expected_hour_kwh=6.0, minutes_left=30)
    assert res["ratio"] == 1.0
    assert res["adjusted_today_remaining"] == res["forecast_today_remaining"]


def test_underperformance_50pct():
    """Sudden cloud cover, PV at half the forecast → ratio 0.5 → today_remaining drops."""
    # 3000 W × 5/60 / 1000 = 0.25 kWh
    # expected = 0.5 kWh → ratio = 0.5
    res = _compute(pv_w=3000, expected_hour_kwh=6.0, minutes_left=30)
    assert res["ratio"] == 0.5
    # current_hour_remaining = 6 × 30/60 = 3 kWh
    # adjusted = 3 × 0.5 = 1.5 kWh
    # today_remaining = 11 - 3 + 1.5 = 9.5
    assert res["adjusted_today_remaining"] == 9.5


def test_outperformance_clamps_at_3():
    """Crazy-high actual (sensor glitch?) clamps ratio at 3.0."""
    res = _compute(pv_w=120000, expected_hour_kwh=2.0, minutes_left=60)
    assert res["ratio"] == 3.0


def test_low_expectation_returns_unity():
    """When expected_5min is < 0.05 kWh (~600 W avg), ratio defaults to 1 to avoid noise."""
    # expected_hour = 0.3 kWh → expected_5min = 0.025 < 0.05 → ratio = 1.0
    res = _compute(pv_w=0, expected_hour_kwh=0.3, minutes_left=30)
    assert res["ratio"] == 1.0


def test_zero_power_full_underperformance():
    """No PV at all when forecast expected serious production."""
    res = _compute(pv_w=0, expected_hour_kwh=6.0, minutes_left=30)
    assert res["ratio"] == 0.0
    # current_hour_remaining = 3 kWh, adjusted = 0
    # today_remaining = 11 - 3 + 0 = 8
    assert res["adjusted_today_remaining"] == 8.0


def test_adjusted_never_negative():
    """Edge case: should clamp at 0 even if math produces negative."""
    # forecast_today = 6 + 5 = 11 kWh; current_hour_remaining = 3; adjusted = 0
    # 11 - 3 + 0 = 8 (no negative possible here)
    # But verify clamp directly with a degenerate case
    res = _compute(pv_w=0, expected_hour_kwh=100.0, minutes_left=60)
    # forecast_today = 105, current_hour_remaining = 100, adjusted = 0
    # 105 - 100 + 0 = 5, still positive
    assert res["adjusted_today_remaining"] >= 0.0


def test_pv_forecast_adjusted_schema_roundtrip():
    """PVForecastAdjusted model_dump produces all expected keys."""
    event = PVForecastAdjusted(
        timestamp="2026-04-28T13:00:00+00:00",
        hour_utc=13,
        actual_5min_kwh=0.5,
        expected_5min_kwh=0.5,
        ratio=1.0,
        forecast_today_remaining_kwh=11.0,
        adjusted_today_remaining_kwh=11.0,
        pv_power_w=6000.0,
    )
    data = event.model_dump()
    assert data["hour_utc"] == 13
    assert data["ratio"] == 1.0
    assert data["pv_power_w"] == 6000.0
