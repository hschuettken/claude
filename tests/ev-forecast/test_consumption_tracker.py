"""Tests for ConsumptionTracker — kWh/100km calculation from mileage + SoC."""

from __future__ import annotations


# conftest.py sets up sys.path
from vehicle import ConsumptionTracker


BATTERY_CAPACITY = 83.0  # Audi A6 e-tron gross


def make_tracker(
    default: float = 22.0,
    min_plausible: float = 5.0,
    max_plausible: float = 60.0,
) -> ConsumptionTracker:
    return ConsumptionTracker(
        battery_capacity_kwh=BATTERY_CAPACITY,
        default_consumption=default,
        min_plausible_consumption=min_plausible,
        max_plausible_consumption=max_plausible,
    )


# ---------------------------------------------------------------------------
# 1. No data → returns default consumption
# ---------------------------------------------------------------------------


def test_default_consumption_when_no_data():
    """Without any measurements, consumption_kwh_per_100km returns the default."""
    tracker = make_tracker(default=22.0)
    assert not tracker.has_data
    # Default is 22.0, bounded to [5.0, 60.0]
    result = tracker.consumption_kwh_per_100km
    assert result == 22.0


# ---------------------------------------------------------------------------
# 2. Basic segment detection
# ---------------------------------------------------------------------------


def test_basic_segment_detection():
    """Driving segment detected when mileage increases and SoC drops."""
    tracker = make_tracker()
    # Initial reading
    result = tracker.update(10000.0, 80.0)
    assert result is None  # First reading, no delta yet

    # Second reading: drove 50 km, SoC dropped from 80% to 70%
    # Energy used = 10/100 * 83 = 8.3 kWh
    # Consumption = 8.3 / 50 * 100 = 16.6 kWh/100km
    result = tracker.update(10050.0, 70.0)
    assert result is not None
    assert tracker.has_data
    assert tracker.measurement_count == 1


def test_no_segment_when_soc_stays_same():
    """No segment is recorded if SoC didn't change (no driving)."""
    tracker = make_tracker()
    tracker.update(10000.0, 60.0)
    result = tracker.update(10010.0, 60.5)  # SoC slightly up, no decrease
    assert result is None


def test_no_segment_when_mileage_stays_same():
    """No segment if mileage doesn't increase (≤1 km delta)."""
    tracker = make_tracker()
    tracker.update(10000.0, 60.0)
    result = tracker.update(10000.5, 55.0)  # < 1.0 km delta
    assert result is None


# ---------------------------------------------------------------------------
# 3. Outlier rejection
# ---------------------------------------------------------------------------


def test_high_consumption_outlier_rejected():
    """Consumption > 60 kWh/100km is rejected as an outlier."""
    tracker = make_tracker(max_plausible=60.0)
    tracker.update(10000.0, 90.0)
    # Drove 1 km but SoC dropped massively (implausible)
    # Energy = 80/100 * 83 = 66.4 kWh, consumption = 66.4/1 * 100 = 6640 kWh/100km
    tracker.update(10001.0, 10.0)
    assert not tracker.has_data


def test_low_consumption_outlier_rejected():
    """Consumption < 5 kWh/100km is rejected (unrealistically efficient)."""
    tracker = make_tracker(min_plausible=5.0)
    tracker.update(10000.0, 50.0)
    # Drove 1000 km but SoC barely dropped (1% = 0.83 kWh → 0.083 kWh/100km)
    tracker.update(11000.0, 49.0)
    assert not tracker.has_data


def test_valid_consumption_is_recorded():
    """A plausible consumption value is stored and counted."""
    tracker = make_tracker(min_plausible=5.0, max_plausible=60.0)
    tracker.update(10000.0, 80.0)
    # 100 km, SoC drops 10% → energy = 8.3 kWh → consumption = 8.3 kWh/100km
    # That's within [5, 60]
    result = tracker.update(10100.0, 70.0)
    assert result is not None
    assert tracker.has_data
    assert tracker.measurement_count == 1


# ---------------------------------------------------------------------------
# 4. Rolling average
# ---------------------------------------------------------------------------


def test_rolling_average_updates_with_measurements():
    """After several measurements, consumption reflects recent driving data."""
    tracker = make_tracker(default=22.0, min_plausible=5.0, max_plausible=60.0)

    # Simulate 5 driving segments, all at ~22 kWh/100km
    # 100 km each, 10% SoC drop each time (83 kWh * 10% = 8.3 kWh → 8.3 kWh/100km)
    mileage = 10000.0
    soc = 100.0
    for i in range(5):
        tracker.update(mileage, soc)
        mileage += 100
        soc -= 10  # 8.3 kWh/100km
        tracker.update(mileage, soc)

    assert tracker.has_data
    assert tracker.measurement_count == 5
    # Consumption should be close to 8.3 kWh/100km (well within [5, 60])
    result = tracker.consumption_kwh_per_100km
    assert 5.0 <= result <= 35.0


def test_rolling_average_bounded_by_plausible_range():
    """consumption_kwh_per_100km is always within [min_plausible, max_plausible]."""
    tracker = ConsumptionTracker(
        battery_capacity_kwh=BATTERY_CAPACITY,
        default_consumption=22.0,
        min_plausible_consumption=17.0,
        max_plausible_consumption=35.0,
    )
    # Even with no data, result should be bounded
    assert tracker.consumption_kwh_per_100km >= 17.0
    assert tracker.consumption_kwh_per_100km <= 35.0


# ---------------------------------------------------------------------------
# 5. Edge cases: zero distance, zero delta, negative delta
# ---------------------------------------------------------------------------


def test_zero_soc_change_no_segment():
    """Zero SoC change → no driving segment recorded."""
    tracker = make_tracker()
    tracker.update(10000.0, 50.0)
    result = tracker.update(10100.0, 50.0)  # SoC unchanged
    assert result is None
    assert not tracker.has_data


def test_soc_increase_no_segment():
    """SoC increase (charging) doesn't produce a driving segment."""
    tracker = make_tracker()
    tracker.update(10000.0, 50.0)
    result = tracker.update(10000.0, 80.0)  # SoC went up (charged)
    assert result is None


def test_none_inputs_handled_gracefully():
    """None mileage or SoC values are handled without errors."""
    tracker = make_tracker()
    result = tracker.update(None, 50.0)
    assert result is None
    result = tracker.update(10000.0, None)
    assert result is None
    assert not tracker.has_data


# ---------------------------------------------------------------------------
# 6. Serialization round-trip
# ---------------------------------------------------------------------------


def test_to_dict_and_from_dict():
    """ConsumptionTracker can be serialized to dict and restored."""
    tracker = make_tracker(default=22.0, min_plausible=5.0, max_plausible=60.0)
    # Add a measurement
    tracker.update(10000.0, 80.0)
    tracker.update(10100.0, 70.0)  # 8.3 kWh/100km

    d = tracker.to_dict()
    assert "history" in d
    assert "last_mileage" in d
    assert "last_soc" in d

    restored = ConsumptionTracker.from_dict(
        d,
        capacity=BATTERY_CAPACITY,
        default=22.0,
        min_plausible=5.0,
        max_plausible=60.0,
    )
    assert restored.measurement_count == tracker.measurement_count
    assert restored._last_mileage == tracker._last_mileage
    assert restored._last_soc == tracker._last_soc
