"""Tests for accuracy.py — AccuracyRow arithmetic + edge cases."""

from datetime import date

from accuracy import AccuracyRow


def test_mae_calculation_over_predicted():
    row = AccuracyRow(
        target_date=date(2026, 4, 27),
        predicted_demand_kwh=12.0,
        actual_demand_kwh=10.0,
        predicted_pv_kwh=8.0,
        actual_pv_kwh=7.0,
        predicted_grid_kwh=4.0,
        actual_grid_kwh=3.0,
    )
    assert row.mae_kwh == 2.0
    assert row.bias_kwh == 2.0  # over-predicted by 2


def test_bias_negative_means_under_predicted():
    row = AccuracyRow(
        target_date=date(2026, 4, 27),
        predicted_demand_kwh=8.0,
        actual_demand_kwh=12.0,
        predicted_pv_kwh=4.0,
        actual_pv_kwh=4.0,
        predicted_grid_kwh=4.0,
        actual_grid_kwh=8.0,
    )
    assert row.bias_kwh == -4.0
    assert row.mae_kwh == 4.0


def test_perfect_prediction():
    row = AccuracyRow(
        target_date=date(2026, 4, 27),
        predicted_demand_kwh=10.0,
        actual_demand_kwh=10.0,
        predicted_pv_kwh=6.0,
        actual_pv_kwh=6.0,
        predicted_grid_kwh=4.0,
        actual_grid_kwh=4.0,
    )
    assert row.mae_kwh == 0.0
    assert row.bias_kwh == 0.0
