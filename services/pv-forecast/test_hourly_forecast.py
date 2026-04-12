"""Test for hourly forecast publishing."""

from datetime import datetime, timezone

from forecast import FullForecast, ArrayForecast, DayForecast, HourlyForecast
from main import PVForecastService


def test_hourly_list_merges_east_west():
    """Test that _build_hourly_list merges east + west hourly data correctly."""
    # Create a mock service
    service = PVForecastService()

    # Create mock hourly data for east array
    east_hourly = [
        HourlyForecast(
            time=datetime(2026, 4, 12, 8, 0, 0, tzinfo=timezone.utc), kwh=0.5
        ),
        HourlyForecast(
            time=datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc), kwh=1.2
        ),
        HourlyForecast(
            time=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc), kwh=2.3
        ),
    ]
    east_day = DayForecast(
        date=datetime(2026, 4, 12).date(),
        total_kwh=4.0,
        hourly=east_hourly,
    )
    east_forecast = ArrayForecast(array_name="east", today=east_day)

    # Create mock hourly data for west array (same hours, different values)
    west_hourly = [
        HourlyForecast(
            time=datetime(2026, 4, 12, 8, 0, 0, tzinfo=timezone.utc), kwh=0.3
        ),
        HourlyForecast(
            time=datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc), kwh=0.8
        ),
        HourlyForecast(
            time=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc), kwh=1.7
        ),
    ]
    west_day = DayForecast(
        date=datetime(2026, 4, 12).date(),
        total_kwh=2.8,
        hourly=west_hourly,
    )
    west_forecast = ArrayForecast(array_name="west", today=west_day)

    # Create full forecast
    full_forecast = FullForecast(
        timestamp=datetime.now(timezone.utc),
        east=east_forecast,
        west=west_forecast,
    )

    # Call _build_hourly_list
    result = service._build_hourly_list(full_forecast, "today")

    # Verify structure and values
    assert len(result) == 3, f"Expected 3 hours, got {len(result)}"

    # Check hour 8: 0.5 + 0.3 = 0.8
    assert result[0]["hour"] == 8
    assert result[0]["kwh"] == 0.8  # rounded to 3 decimals
    assert result[0]["confidence"] == 0.8

    # Check hour 9: 1.2 + 0.8 = 2.0
    assert result[1]["hour"] == 9
    assert result[1]["kwh"] == 2.0
    assert result[1]["confidence"] == 0.8

    # Check hour 10: 2.3 + 1.7 = 4.0
    assert result[2]["hour"] == 10
    assert result[2]["kwh"] == 4.0
    assert result[2]["confidence"] == 0.8


def test_hourly_list_empty_when_no_data():
    """Test that _build_hourly_list returns empty list when no hourly data exists."""
    service = PVForecastService()

    # Create forecast with no hourly data
    full_forecast = FullForecast(
        timestamp=datetime.now(timezone.utc),
        east=ArrayForecast(array_name="east", today=None),
        west=ArrayForecast(array_name="west", today=None),
    )

    result = service._build_hourly_list(full_forecast, "today")
    assert result == []


def test_hourly_list_east_only():
    """Test with only east array data."""
    service = PVForecastService()

    east_hourly = [
        HourlyForecast(
            time=datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc), kwh=3.5
        ),
    ]
    east_day = DayForecast(
        date=datetime(2026, 4, 12).date(),
        total_kwh=3.5,
        hourly=east_hourly,
    )

    full_forecast = FullForecast(
        timestamp=datetime.now(timezone.utc),
        east=ArrayForecast(array_name="east", today=east_day),
        west=ArrayForecast(array_name="west", today=None),
    )

    result = service._build_hourly_list(full_forecast, "today")
    assert len(result) == 1
    assert result[0]["hour"] == 12
    assert result[0]["kwh"] == 3.5
