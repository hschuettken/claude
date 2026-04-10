"""Advanced unit tests for schedule manager mode overlays (#1041).

Tests verify:
  1. Default schedule returns expected setpoints
  2. Comfort overlay takes priority over schedule
  3. Away mode returns minimum setpoint
  4. Boost mode returns maximum comfort
  5. Overlay expiry and fallback
  6. Mode interactions and priority rules
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from schedule_manager import ComfortOverlay, HeatingMode, ScheduleManager, ScheduleSlot


def _dt(weekday: int, hour: int, minute: int = 0) -> datetime:
    """Return a datetime with given weekday (Mon=0) and time.

    Uses ISO week 2024-W01 as reference: 2024-01-01 is Monday.
    """
    base = datetime(2024, 1, 1)
    return base + timedelta(days=weekday, hours=hour, minutes=minute)


# ---------------------------------------------------------------------------
# Test #1: Default schedule returns expected setpoint
# ---------------------------------------------------------------------------


class TestDefaultScheduleReturnsSetpoint:
    """Test that DEFAULT_SCHEDULE is applied correctly in AUTO mode."""

    def test_monday_morning_6am_in_schedule(self):
        """Monday 06:00 falls in weekday morning slot → 21°C."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(0, 6, 0))
        assert sp == 21.0

    def test_monday_8am_boundary(self):
        """Monday at 08:00 (slot end time) → 21°C (inclusive)."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(0, 8, 0))
        assert sp == 21.0

    def test_monday_before_morning_slot(self):
        """Monday 05:59 before morning slot → eco setback (18°C)."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(0, 5, 59))
        assert sp == ScheduleManager.ECO_SETBACK

    def test_monday_evening_5pm_to_10pm(self):
        """Monday 18:00 to 22:00 falls in evening slot → 21°C."""
        mgr = ScheduleManager()
        sp_early = mgr.get_setpoint(_dt(0, 17, 0))
        sp_mid = mgr.get_setpoint(_dt(0, 20, 0))
        sp_late = mgr.get_setpoint(_dt(0, 22, 0))
        assert sp_early == 21.0
        assert sp_mid == 21.0
        assert sp_late == 21.0

    def test_monday_midday_between_slots(self):
        """Monday 12:00 between morning and evening slots → eco."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(0, 12, 0))
        assert sp == ScheduleManager.ECO_SETBACK

    def test_saturday_8am_to_10pm(self):
        """Saturday 12:00 falls in weekend slot (08:00-22:00) → 21°C."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(5, 12, 0))
        assert sp == 21.0

    def test_saturday_early_morning_before_weekend(self):
        """Saturday 07:00 before weekend slot start → eco."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(5, 7, 0))
        assert sp == ScheduleManager.ECO_SETBACK

    def test_sunday_afternoon(self):
        """Sunday 15:00 in weekend slot → 21°C."""
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(6, 15, 0))
        assert sp == 21.0


# ---------------------------------------------------------------------------
# Test #2: Comfort overlay takes priority
# ---------------------------------------------------------------------------


class TestComfortOverlayTakesPriority:
    """Test that active comfort overlay returns its setpoint."""

    def test_overlay_returns_overlay_setpoint(self):
        """Active overlay returns overlay setpoint, not schedule."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(setpoint=24.0, duration_minutes=60)
        sp = mgr.get_setpoint()
        assert sp == 24.0

    def test_overlay_in_auto_mode(self):
        """Comfort overlay works even in AUTO mode."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.AUTO)
        mgr.set_comfort_overlay(23.5, 30)
        sp = mgr.get_setpoint()
        assert sp == 23.5

    def test_overlay_returns_higher_value(self):
        """Overlay with high value overrides lower schedule."""
        mgr = ScheduleManager()
        mgr.replace_schedule(
            [ScheduleSlot(time(0, 0), time(23, 59), 19.0, list(range(7)))]
        )
        mgr.set_comfort_overlay(25.0, 60)
        sp = mgr.get_setpoint()
        assert sp == 25.0

    def test_overlay_returns_lower_value_still_applies(self):
        """Overlay lower than schedule still applies (override property)."""
        mgr = ScheduleManager()
        mgr.replace_schedule(
            [ScheduleSlot(time(0, 0), time(23, 59), 22.0, list(range(7)))]
        )
        mgr.set_comfort_overlay(20.0, 60)
        sp = mgr.get_setpoint()
        assert sp == 20.0

    def test_overlay_persists_across_schedule_changes(self):
        """Overlay remains active even if schedule is replaced."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(24.0, 60)
        mgr.replace_schedule(
            [ScheduleSlot(time(0, 0), time(23, 59), 18.0, list(range(7)))]
        )
        sp = mgr.get_setpoint()
        assert sp == 24.0

    def test_overlay_with_specific_reason(self):
        """Overlay can be set with a reason string."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(23.0, 30, reason="guest_arriving")
        assert mgr.comfort_overlay.reason == "guest_arriving"
        status = mgr.get_status()
        assert status["comfort_overlay"]["reason"] == "guest_arriving"


# ---------------------------------------------------------------------------
# Test #3: Away mode returns eco temperature
# ---------------------------------------------------------------------------


class TestAwayModeReturnsEcoTemp:
    """Test that AWAY mode always returns minimum setpoint."""

    def test_away_mode_during_scheduled_hours(self):
        """AWAY mode returns eco, even during normally-scheduled comfort hours."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.AWAY)
        sp = mgr.get_setpoint(_dt(0, 7, 0))  # Would be 21°C in AUTO
        assert sp == ScheduleManager.ECO_SETBACK

    def test_away_mode_outside_scheduled_hours(self):
        """AWAY mode returns eco outside schedule too."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.AWAY)
        sp = mgr.get_setpoint(_dt(0, 3, 0))
        assert sp == ScheduleManager.ECO_SETBACK

    def test_away_mode_ignores_overlay(self):
        """AWAY mode takes precedence over comfort overlay."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.AWAY)
        mgr.set_comfort_overlay(25.0, 60)
        sp = mgr.get_setpoint()
        # AWAY should still return eco, not overlay
        assert sp == ScheduleManager.ECO_SETBACK

    def test_away_mode_constant_across_week(self):
        """AWAY mode returns same setpoint Mon-Sun."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.AWAY)
        sps = [mgr.get_setpoint(_dt(day, 12)) for day in range(7)]
        for sp in sps:
            assert sp == ScheduleManager.ECO_SETBACK


# ---------------------------------------------------------------------------
# Test #4: Boost mode returns maximum
# ---------------------------------------------------------------------------


class TestBoostModeReturnsMaxComfort:
    """Test that BOOST mode adds delta to scheduled setpoint."""

    def test_boost_during_scheduled_hours(self):
        """BOOST during schedule: schedule + delta."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.BOOST)
        sp = mgr.get_setpoint(_dt(0, 7, 0))  # Mon 07:00 → sched 21°C
        assert sp == pytest.approx(21.0 + ScheduleManager.BOOST_DELTA)

    def test_boost_outside_scheduled_hours(self):
        """BOOST outside schedule: eco_setback + delta."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.BOOST)
        sp = mgr.get_setpoint(_dt(0, 3, 0))  # Mon 03:00 → eco 18°C
        assert sp == pytest.approx(18.0 + ScheduleManager.BOOST_DELTA)

    def test_boost_delta_is_two_degrees(self):
        """BOOST_DELTA constant is 2.0°C."""
        assert ScheduleManager.BOOST_DELTA == 2.0

    def test_boost_ignores_overlay(self):
        """BOOST mode does not respect comfort overlay."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.BOOST)
        mgr.set_comfort_overlay(25.0, 60)
        sp = mgr.get_setpoint(_dt(0, 7, 0))
        # Should still be schedule + delta, not overlay
        expected = 21.0 + ScheduleManager.BOOST_DELTA
        assert sp == pytest.approx(expected)

    def test_boost_multiple_days(self):
        """BOOST applies consistently across the week."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.BOOST)
        sp_mon = mgr.get_setpoint(_dt(0, 7, 0))
        sp_sat = mgr.get_setpoint(_dt(5, 12, 0))
        # Both should be schedule + delta
        assert sp_mon == pytest.approx(21.0 + 2.0)
        assert sp_sat == pytest.approx(21.0 + 2.0)


# ---------------------------------------------------------------------------
# Test #5: Overlay expiry and fallback
# ---------------------------------------------------------------------------


class TestOverlayExpiryFallsBack:
    """Test that expired overlay reverts to schedule."""

    def test_expired_overlay_clears(self):
        """Overlay past expiry time is cleared."""
        mgr = ScheduleManager()
        mgr.comfort_overlay = ComfortOverlay(
            setpoint=24.0,
            until=datetime.now() - timedelta(minutes=1),
            reason="test",
        )
        # Call get_setpoint, which checks expiry
        sp = mgr.get_setpoint()
        # After get_setpoint, overlay should be None
        assert mgr.comfort_overlay is None

    def test_expired_overlay_reverts_to_schedule(self):
        """After expiry, schedule is used (not the old overlay value)."""
        mgr = ScheduleManager()
        mgr.comfort_overlay = ComfortOverlay(
            setpoint=24.0,
            until=datetime.now() - timedelta(minutes=1),
            reason="test",
        )
        sp = mgr.get_setpoint(_dt(0, 7, 0))  # Use a scheduled time
        # Should be schedule, not overlay (24.0)
        assert sp == 21.0

    def test_active_overlay_not_expired(self):
        """Overlay valid for 60 minutes is not cleared until then."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(24.0, 60)
        # Call immediately
        sp1 = mgr.get_setpoint()
        assert sp1 == 24.0
        assert mgr.comfort_overlay is not None

    def test_overlay_expiry_multiple_calls(self):
        """Overlay expires on a specific call, then subsequent calls use schedule."""
        mgr = ScheduleManager()
        # Overlay expires 1 minute ago
        mgr.comfort_overlay = ComfortOverlay(
            setpoint=24.0,
            until=datetime.now() - timedelta(minutes=1),
            reason="test",
        )
        # First call clears it
        sp1 = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp1 == 21.0
        assert mgr.comfort_overlay is None
        # Second call still uses schedule
        sp2 = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp2 == 21.0

    def test_clear_comfort_overlay_manually(self):
        """Can manually clear overlay before expiry."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(24.0, 120)  # 120 minutes (not expired)
        assert mgr.comfort_overlay is not None
        mgr.clear_comfort_overlay()
        assert mgr.comfort_overlay is None


# ---------------------------------------------------------------------------
# Test #6: Priority and interaction rules
# ---------------------------------------------------------------------------


class TestPriorityAndInteractionRules:
    """Test priority rules: boost > overlay > mode > schedule."""

    def test_eco_mode_beats_overlay(self):
        """ECO mode takes priority over comfort overlay."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.ECO)
        mgr.set_comfort_overlay(25.0, 60)
        sp = mgr.get_setpoint()
        # ECO wins
        assert sp == ScheduleManager.ECO_SETBACK

    def test_comfort_mode_at_least_21(self):
        """COMFORT mode enforces minimum 21°C."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.COMFORT)
        mgr.replace_schedule(
            [ScheduleSlot(time(0, 0), time(23, 59), 19.0, list(range(7)))]
        )
        sp = mgr.get_setpoint()
        assert sp == 21.0

    def test_comfort_mode_preserves_higher(self):
        """COMFORT mode keeps higher scheduled setpoint."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.COMFORT)
        mgr.replace_schedule(
            [ScheduleSlot(time(0, 0), time(23, 59), 22.0, list(range(7)))]
        )
        sp = mgr.get_setpoint()
        assert sp == 22.0

    def test_mode_transition_auto_to_eco(self):
        """Transitioning from AUTO to ECO immediately changes setpoint."""
        mgr = ScheduleManager()
        sp_auto = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp_auto == 21.0

        mgr.set_mode(HeatingMode.ECO)
        sp_eco = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp_eco == ScheduleManager.ECO_SETBACK

    def test_mode_transition_back_to_auto(self):
        """Switching back to AUTO restores schedule."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.ECO)
        mgr.set_mode(HeatingMode.AUTO)
        sp = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp == 21.0

    def test_get_status_reflects_mode(self):
        """get_status includes current mode."""
        mgr = ScheduleManager()
        mgr.set_mode(HeatingMode.BOOST)
        status = mgr.get_status()
        assert status["mode"] == "boost"

    def test_get_status_includes_current_setpoint(self):
        """get_status includes current_setpoint calculated now."""
        mgr = ScheduleManager()
        status = mgr.get_status()
        assert "current_setpoint" in status
        assert isinstance(status["current_setpoint"], float)

    def test_schedule_replacement_affects_setpoint(self):
        """Replacing schedule changes what get_setpoint returns."""
        mgr = ScheduleManager()
        new_schedule = [ScheduleSlot(time(0, 0), time(23, 59), 20.5, list(range(7)))]
        mgr.replace_schedule(new_schedule)
        sp = mgr.get_setpoint(_dt(0, 7, 0))
        assert sp == 20.5


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCasesAndRobustness:
    """Test edge cases and numerical stability."""

    def test_midnight_boundary(self):
        """Schedule edge cases around midnight."""
        mgr = ScheduleManager()
        # 23:59
        sp_late = mgr.get_setpoint(_dt(0, 23, 59))
        # 00:00 (next day)
        sp_early = mgr.get_setpoint(_dt(1, 0, 0))
        # Both outside schedule → eco
        assert sp_late == ScheduleManager.ECO_SETBACK
        assert sp_early == ScheduleManager.ECO_SETBACK

    def test_daylight_saving_time_none(self):
        """Schedule uses local time, no DST adjustment needed in logic."""
        # This is more of a note — the code uses time() and weekday() which are local
        mgr = ScheduleManager()
        sp = mgr.get_setpoint(_dt(0, 12, 0))
        assert isinstance(sp, float)

    def test_multiple_overlays_only_one_active(self):
        """Only one overlay can be active at a time."""
        mgr = ScheduleManager()
        mgr.set_comfort_overlay(24.0, 30)
        first_overlay = mgr.comfort_overlay
        mgr.set_comfort_overlay(25.0, 30)
        second_overlay = mgr.comfort_overlay
        # They should be different instances
        assert first_overlay is not second_overlay

    def test_schedule_with_overlapping_slots(self):
        """If two slots overlap, first match wins."""
        mgr = ScheduleManager()
        slot1 = ScheduleSlot(time(10, 0), time(15, 0), 21.0, [0])
        slot2 = ScheduleSlot(time(12, 0), time(16, 0), 22.0, [0])
        mgr.replace_schedule([slot1, slot2])
        sp = mgr.get_setpoint(_dt(0, 13, 0))  # Between both
        # First match in list is slot1 → 21°C
        assert sp == 21.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
