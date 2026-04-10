"""Unit tests for schedule_manager.py (#1041)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from schedule_manager import ComfortOverlay, HeatingMode, ScheduleManager, ScheduleSlot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(weekday: int, hour: int, minute: int = 0) -> datetime:
    """Return a datetime with the given weekday (Mon=0) and time.

    Uses ISO week 2024-W01 as a stable reference: 2024-01-01 is Monday.
    """
    base = datetime(2024, 1, 1)  # Monday
    return base + timedelta(days=weekday, hours=hour, minutes=minute)


# ---------------------------------------------------------------------------
# Default schedule tests
# ---------------------------------------------------------------------------


def test_weekday_morning_in_schedule():
    """Weekday 07:00 falls in the morning slot → 21°C."""
    mgr = ScheduleManager()
    sp = mgr.get_setpoint(_dt(0, 7))  # Monday 07:00
    assert sp == 21.0


def test_weekday_evening_in_schedule():
    """Weekday 19:00 falls in the evening slot → 21°C."""
    mgr = ScheduleManager()
    sp = mgr.get_setpoint(_dt(1, 19))  # Tuesday 19:00
    assert sp == 21.0


def test_outside_schedule_returns_eco():
    """Weekday 03:00 is outside all slots → eco setback (18°C)."""
    mgr = ScheduleManager()
    sp = mgr.get_setpoint(_dt(0, 3))  # Monday 03:00
    assert sp == ScheduleManager.ECO_SETBACK


def test_weekend_midday_in_schedule():
    """Saturday 12:00 falls in weekend slot → 21°C."""
    mgr = ScheduleManager()
    sp = mgr.get_setpoint(_dt(5, 12))  # Saturday 12:00
    assert sp == 21.0


def test_weekend_early_morning_outside_schedule():
    """Saturday 06:30 is before weekend slot start (08:00) → eco."""
    mgr = ScheduleManager()
    sp = mgr.get_setpoint(_dt(5, 6, 30))
    assert sp == ScheduleManager.ECO_SETBACK


# ---------------------------------------------------------------------------
# Mode override tests
# ---------------------------------------------------------------------------


def test_eco_mode_overrides_schedule():
    """ECO mode always returns setback, even during scheduled hours."""
    mgr = ScheduleManager()
    mgr.set_mode(HeatingMode.ECO)
    sp = mgr.get_setpoint(_dt(0, 7))  # Would be 21°C in AUTO
    assert sp == ScheduleManager.ECO_SETBACK


def test_away_mode_overrides_schedule():
    """AWAY mode always returns setback."""
    mgr = ScheduleManager()
    mgr.set_mode(HeatingMode.AWAY)
    sp = mgr.get_setpoint(_dt(0, 7))
    assert sp == ScheduleManager.ECO_SETBACK


def test_boost_mode_adds_delta():
    """BOOST adds BOOST_DELTA (2°C) on top of scheduled setpoint."""
    mgr = ScheduleManager()
    mgr.set_mode(HeatingMode.BOOST)
    sp = mgr.get_setpoint(_dt(0, 7))  # Schedule = 21°C
    assert sp == pytest.approx(21.0 + ScheduleManager.BOOST_DELTA)


def test_boost_mode_outside_schedule():
    """BOOST outside scheduled hours: eco_setback + BOOST_DELTA."""
    mgr = ScheduleManager()
    mgr.set_mode(HeatingMode.BOOST)
    sp = mgr.get_setpoint(_dt(0, 3))
    assert sp == pytest.approx(
        ScheduleManager.ECO_SETBACK + ScheduleManager.BOOST_DELTA
    )


def test_comfort_mode_at_least_21():
    """COMFORT mode never drops below 21°C, even if schedule would be lower."""
    mgr = ScheduleManager()
    # Add a slot with a low setpoint
    mgr.replace_schedule([ScheduleSlot(time(6, 0), time(8, 0), 19.0, list(range(7)))])
    mgr.set_mode(HeatingMode.COMFORT)
    sp = mgr.get_setpoint(_dt(0, 7))
    assert sp == 21.0


def test_comfort_mode_preserves_higher_setpoint():
    """COMFORT mode keeps the scheduled setpoint if it's already >= 21°C."""
    mgr = ScheduleManager()
    mgr.replace_schedule([ScheduleSlot(time(6, 0), time(22, 0), 22.5, list(range(7)))])
    mgr.set_mode(HeatingMode.COMFORT)
    sp = mgr.get_setpoint(_dt(0, 12))
    assert sp == 22.5


# ---------------------------------------------------------------------------
# Comfort overlay tests
# ---------------------------------------------------------------------------


def test_comfort_overlay_raises_setpoint():
    """Active comfort overlay returns its setpoint regardless of schedule."""
    mgr = ScheduleManager()
    mgr.set_comfort_overlay(24.0, duration_minutes=60)
    sp = mgr.get_setpoint()
    assert sp == 24.0


def test_comfort_overlay_expires():
    """Expired comfort overlay is cleared and schedule takes over."""
    mgr = ScheduleManager()
    # Inject already-expired overlay (until = 1 minute ago in real wall-clock time)
    mgr.comfort_overlay = ComfortOverlay(
        setpoint=24.0,
        until=datetime.now() - timedelta(minutes=1),
        reason="test",
    )
    # Call get_setpoint with no arg so it uses datetime.now() — overlay is expired
    sp = mgr.get_setpoint()
    # Setpoint may be eco (outside hours) or scheduled — either way NOT 24.0
    assert sp != 24.0
    # Overlay should have been cleared
    assert mgr.comfort_overlay is None


def test_comfort_overlay_ignores_mode_eco():
    """In ECO mode the overlay is NOT applied — eco wins over overlay."""
    mgr = ScheduleManager()
    mgr.set_mode(HeatingMode.ECO)
    mgr.set_comfort_overlay(24.0, duration_minutes=60)
    sp = mgr.get_setpoint()
    # ECO always wins
    assert sp == ScheduleManager.ECO_SETBACK


def test_clear_comfort_overlay():
    """Explicitly clearing the overlay makes it None."""
    mgr = ScheduleManager()
    mgr.set_comfort_overlay(24.0, 30)
    assert mgr.comfort_overlay is not None
    mgr.clear_comfort_overlay()
    assert mgr.comfort_overlay is None


# ---------------------------------------------------------------------------
# Schedule mutation tests
# ---------------------------------------------------------------------------


def test_add_slot_extends_schedule():
    """Adding a slot increases schedule length and is respected."""
    mgr = ScheduleManager()
    original_len = len(mgr.schedule)
    extra = ScheduleSlot(time(12, 0), time(14, 0), 22.0, [0])  # Mon lunch
    mgr.add_schedule_slot(extra)
    assert len(mgr.schedule) == original_len + 1
    sp = mgr.get_setpoint(_dt(0, 13))  # Monday 13:00
    assert sp == 22.0


def test_replace_schedule():
    """replace_schedule swaps out all slots."""
    mgr = ScheduleManager()
    new_schedule = [ScheduleSlot(time(0, 0), time(23, 59), 20.0, list(range(7)))]
    mgr.replace_schedule(new_schedule)
    sp = mgr.get_setpoint(_dt(3, 3))  # Any time
    assert sp == 20.0


# ---------------------------------------------------------------------------
# get_status tests
# ---------------------------------------------------------------------------


def test_get_status_no_overlay():
    """get_status returns mode, setpoint, and None overlay when no overlay set."""
    mgr = ScheduleManager()
    status = mgr.get_status()
    assert status["mode"] == "auto"
    assert "current_setpoint" in status
    assert status["comfort_overlay"] is None


def test_get_status_with_overlay():
    """get_status includes overlay details when active."""
    mgr = ScheduleManager()
    mgr.set_comfort_overlay(23.5, 30, reason="guest_visit")
    status = mgr.get_status()
    assert status["comfort_overlay"] is not None
    assert status["comfort_overlay"]["setpoint"] == 23.5
    assert status["comfort_overlay"]["reason"] == "guest_visit"
    assert "until" in status["comfort_overlay"]
