"""Tests for patterns._median_time + sparse-data fallback (S6b)."""

from datetime import time
from unittest.mock import MagicMock

from patterns import _median_time, nicole_commute_pattern


def test_median_time_simple():
    times = [time(7, 0), time(7, 30), time(8, 0)]
    assert _median_time(times) == time(7, 30)


def test_median_time_odd_count():
    times = [time(6, 45), time(7, 15), time(7, 0), time(7, 30), time(8, 0)]
    assert _median_time(times) == time(7, 15)


def test_median_time_even_count():
    times = [time(6, 0), time(8, 0)]
    assert _median_time(times) == time(7, 0)


def test_pattern_returns_unlearned_when_sparse():
    """<5 samples per kind should return learned=False."""
    influx = MagicMock()
    influx.query_raw.return_value = []
    result = nicole_commute_pattern(influx)
    assert result["learned"] is False
    assert result["samples_dep"] == 0
    assert result["samples_arr"] == 0
    assert result["median_departure"] is None


def test_pattern_returns_unlearned_on_query_error():
    influx = MagicMock()
    influx.query_raw.side_effect = RuntimeError("influx down")
    result = nicole_commute_pattern(influx)
    assert result["learned"] is False
