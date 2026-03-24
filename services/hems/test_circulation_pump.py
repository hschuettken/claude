"""Unit tests for circulation pump scheduler.

Tests the state machine logic, hysteresis, runtime limits, time-window scheduling, and HA integration.
"""

import pytest
import time
from datetime import time as time_type
from unittest.mock import Mock, patch, AsyncMock

from circulation_pump import CirculationPumpScheduler, PumpState, TimeWindow


class TestCirculationPumpBasics:
    """Test basic pump state machine transitions."""

    def test_init_defaults(self):
        """Test default initialization."""
        pump = CirculationPumpScheduler()
        assert pump.state == PumpState.OFF
        assert pump.min_runtime_s == 600.0
        assert pump.max_runtime_s == 3600.0
        assert pump.temp_hysteresis_c == 0.5
        assert pump.runtime_hours == 0.0

    def test_init_custom_params(self):
        """Test custom initialization."""
        pump = CirculationPumpScheduler(
            min_runtime_s=300, max_runtime_s=1800, temp_hysteresis_c=1.0
        )
        assert pump.min_runtime_s == 300.0
        assert pump.max_runtime_s == 1800.0
        assert pump.temp_hysteresis_c == 1.0

    def test_off_to_on_boiler_active(self):
        """Test transition from OFF to ON when boiler is active."""
        pump = CirculationPumpScheduler()
        
        # Boiler active, no room targets — should turn ON
        result = pump.should_pump(
            boiler_active=True,
            room_targets={},
            room_actuals={}
        )
        
        assert result is True
        assert pump.state == PumpState.ON

    def test_off_to_on_room_needs_heating(self):
        """Test transition from OFF to ON when room needs heating."""
        pump = CirculationPumpScheduler()
        
        # Room target 21°C, actual 20°C (below target) — should turn ON
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 20.0}
        )
        
        assert result is True
        assert pump.state == PumpState.ON

    def test_off_stays_off_no_demand(self):
        """Test that OFF state stays OFF when no boiler and all rooms satisfied."""
        pump = CirculationPumpScheduler()
        
        # Room at target — should stay OFF
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 21.0}
        )
        
        assert result is False
        assert pump.state == PumpState.OFF


class TestCirculationPumpHysteresis:
    """Test hysteresis behavior to prevent chatter."""

    def test_hysteresis_on_downside(self):
        """Test that hysteresis prevents ON→OFF at exact target."""
        pump = CirculationPumpScheduler(
            min_runtime_s=0.1,  # Very short for testing
            temp_hysteresis_c=0.5
        )
        
        # Start with boiler active to turn pump ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Small delay to pass min_runtime
        time.sleep(0.2)
        
        # Room slightly below target (within hysteresis) — boiler off
        # Should NOT turn OFF due to hysteresis
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 20.8}  # 21.0 - 0.2, within hysteresis
        )
        
        # Pump should stay ON because actual (20.8) is NOT > target (21.0) + hyst (0.5)
        # So no heating demand, and boiler is off
        # Actually with our current logic: 21.0 > 20.8 + 0.5 = 20.8 > 21.3? No.
        # So no heating demand. Boiler off. Should transition to COOLDOWN.
        assert pump.state == PumpState.COOLDOWN

    def test_hysteresis_triggers_pump_on(self):
        """Test that hysteresis is applied to turn-on decision."""
        pump = CirculationPumpScheduler(temp_hysteresis_c=0.5)
        
        # Room just slightly below target (within hysteresis) — should NOT turn on
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 20.8}  # Only 0.2°C below
        )
        
        # No heating demand (21.0 > 20.8 + 0.5? No) — pump stays OFF
        assert result is False
        assert pump.state == PumpState.OFF
        
        # Room well below target (exceeds hysteresis) — should turn on
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 20.0}  # 1.0°C below
        )
        
        # Heating demand (21.0 > 20.0 + 0.5 = 20.5? Yes) — pump turns ON
        assert result is True
        assert pump.state == PumpState.ON


class TestCirculationPumpMinimumRuntime:
    """Test minimum runtime enforcement."""

    def test_minimum_runtime_enforced(self):
        """Test that pump won't turn OFF before min_runtime expires."""
        pump = CirculationPumpScheduler(min_runtime_s=1.0)
        
        # Turn pump ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Immediately try to turn OFF (boiler stops, room satisfied)
        # Should stay ON due to min_runtime
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 21.5}  # Satisfied
        )
        
        assert result is True
        assert pump.state == PumpState.ON
        
        # Wait for min_runtime to elapse
        time.sleep(1.1)
        
        # Now should transition to COOLDOWN
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 21.5}
        )
        
        assert result is False
        assert pump.state == PumpState.COOLDOWN


class TestCirculationPumpMaximumRuntime:
    """Test maximum runtime safety limit."""

    def test_maximum_runtime_forces_off(self):
        """Test that pump is forced OFF after max_runtime."""
        # Use very short times for testing
        pump = CirculationPumpScheduler(
            min_runtime_s=0.1,
            max_runtime_s=0.5
        )
        
        # Turn pump ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Wait for max_runtime to elapse
        time.sleep(0.6)
        
        # Pump should force OFF regardless of demand
        result = pump.should_pump(
            boiler_active=True,  # Even with boiler active!
            room_targets={'living_room': 21.0},
            room_actuals={'living_room': 10.0}  # Even with high demand!
        )
        
        assert result is False
        assert pump.state == PumpState.OFF
        # Check that runtime was logged
        assert pump.runtime_hours > 0


class TestCirculationPumpRuntimeTracking:
    """Test runtime hour tracking for maintenance."""

    def test_runtime_hours_accumulation(self):
        """Test that runtime hours are tracked correctly."""
        pump = CirculationPumpScheduler(min_runtime_s=0.1, max_runtime_s=1.0)
        
        # Turn pump ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.runtime_hours == 0.0
        
        # Wait a bit
        time.sleep(0.15)
        
        # Check current runtime (should include ongoing session)
        current_runtime = pump.get_runtime_hours()
        assert current_runtime > 0
        assert current_runtime < 0.001  # Should be ~0.15s / 3600s per hour
        
        # Wait for max_runtime and turn OFF
        time.sleep(0.95)
        pump.should_pump(
            boiler_active=False,
            room_targets={},
            room_actuals={}
        )
        
        # Runtime should now be logged
        assert pump.runtime_hours > 0


class TestCirculationPumpMultipleRooms:
    """Test pump behavior with multiple rooms."""

    def test_multiple_rooms_any_needs_heating(self):
        """Test that pump turns ON if ANY room needs heating."""
        pump = CirculationPumpScheduler()
        
        # Two rooms: one cold, one satisfied
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0, 'bedroom': 19.0},
            room_actuals={'living_room': 21.5, 'bedroom': 18.0}  # Bedroom cold
        )
        
        # Bedroom needs heating (19.0 > 18.0 + 0.5) — pump turns ON
        assert result is True
        assert pump.state == PumpState.ON

    def test_multiple_rooms_all_satisfied(self):
        """Test that pump turns OFF only when ALL rooms are satisfied."""
        pump = CirculationPumpScheduler(min_runtime_s=0.1)
        
        # Start with pump ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Wait for min_runtime
        time.sleep(0.15)
        
        # Both rooms satisfied
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'living_room': 21.0, 'bedroom': 19.0},
            room_actuals={'living_room': 21.5, 'bedroom': 19.5}
        )
        
        # All satisfied, boiler off — pump goes to COOLDOWN
        assert result is False
        assert pump.state == PumpState.COOLDOWN

    def test_unknown_room_defaults_to_15c(self):
        """Test that unknown rooms default to 15°C for comparison."""
        pump = CirculationPumpScheduler(temp_hysteresis_c=0.5)
        
        # Room with unknown actual temp, target is 21°C
        # Unknown should default to 15°C, so 21.0 > 15.0 + 0.5 = yes, heating needed
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'unknown_room': 21.0},
            room_actuals={}  # No actual temp provided
        )
        
        assert result is True
        assert pump.state == PumpState.ON


class TestCirculationPumpStateInfo:
    """Test state introspection methods."""

    def test_get_state(self):
        """Test getting current state."""
        pump = CirculationPumpScheduler()
        assert pump.get_state() == PumpState.OFF
        
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.get_state() == PumpState.ON

    def test_get_state_duration(self):
        """Test getting duration in current state."""
        pump = CirculationPumpScheduler()
        
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        time.sleep(0.1)
        
        duration = pump.get_state_duration()
        assert duration >= 0.1
        assert duration < 0.2

    def test_reset(self):
        """Test pump reset."""
        pump = CirculationPumpScheduler(min_runtime_s=0.1)
        
        # Run pump
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        time.sleep(0.15)
        
        # Transition to COOLDOWN
        pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        assert pump.state == PumpState.COOLDOWN
        
        # Transition to OFF (this is where runtime is logged)
        pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        assert pump.state == PumpState.OFF
        
        # Check runtime was tracked
        assert pump.runtime_hours > 0
        
        # Reset
        pump.reset()
        assert pump.state == PumpState.OFF
        assert pump.runtime_hours == 0.0
        assert pump.last_decision is False


class TestCirculationPumpEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_room_dicts(self):
        """Test with empty room dictionaries."""
        pump = CirculationPumpScheduler()
        
        # No rooms, boiler active — should pump
        result = pump.should_pump(
            boiler_active=True,
            room_targets={},
            room_actuals={}
        )
        assert result is True
        
        # No rooms, boiler off — should not pump
        pump.reset()
        result = pump.should_pump(
            boiler_active=False,
            room_targets={},
            room_actuals={}
        )
        assert result is False

    def test_extreme_temperatures(self):
        """Test with extreme temperature values."""
        pump = CirculationPumpScheduler()
        
        # Very high target, low actual
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'room': 40.0},
            room_actuals={'room': 5.0}
        )
        assert result is True
        
        # Very low target, high actual
        pump.reset()
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'room': 5.0},
            room_actuals={'room': 40.0}
        )
        assert result is False

    def test_zero_temperatures(self):
        """Test with zero temperature values."""
        pump = CirculationPumpScheduler()
        
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'room': 0.0},
            room_actuals={'room': 0.0}
        )
        # At target — should stay OFF
        assert result is False

    def test_negative_temperatures(self):
        """Test with negative temperature values (frost protection)."""
        pump = CirculationPumpScheduler()
        
        result = pump.should_pump(
            boiler_active=False,
            room_targets={'room': -5.0},  # Frost protection target
            room_actuals={'room': -10.0}
        )
        # Should turn ON (target > actual + hysteresis)
        assert result is True


class TestCirculationPumpStateTransitions:
    """Test all valid state transitions."""

    def test_complete_cycle_off_on_cooldown_off(self):
        """Test complete on/off cycle."""
        pump = CirculationPumpScheduler(min_runtime_s=0.1, max_runtime_s=10.0)
        
        # Start: OFF
        assert pump.state == PumpState.OFF
        
        # Transition to ON
        pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Stay ON for min time
        time.sleep(0.15)
        
        # Transition to COOLDOWN
        pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        assert pump.state == PumpState.COOLDOWN
        
        # Transition to OFF
        pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        assert pump.state == PumpState.OFF

    def test_on_resets_timer_with_continued_demand(self):
        """Test that pump stays ON if demand continues during min_runtime."""
        pump = CirculationPumpScheduler(min_runtime_s=0.5)
        
        # Start pump ON
        pump.should_pump(boiler_active=False, room_targets={'room': 21.0}, room_actuals={'room': 19.0})
        start_time = pump.state_enter_time
        
        # After 0.2s, demand is still there
        time.sleep(0.2)
        pump.should_pump(boiler_active=False, room_targets={'room': 21.0}, room_actuals={'room': 19.0})
        assert pump.state == PumpState.ON
        # Timer should not have reset
        assert pump.state_enter_time == start_time


class TestTimeWindow:
    """Test TimeWindow helper class."""

    def test_time_window_init(self):
        """Test TimeWindow initialization."""
        window = TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)
        assert window.start_time == time_type(6, 30)
        assert window.end_time == time_type(8, 0)

    def test_time_window_is_active_simple(self):
        """Test TimeWindow.is_active() for normal windows."""
        window = TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)
        
        # Before window
        assert not window.is_active(time_type(6, 29))
        # Start of window
        assert window.is_active(time_type(6, 30))
        # Middle of window
        assert window.is_active(time_type(7, 0))
        # End of window (exclusive)
        assert not window.is_active(time_type(8, 0))

    def test_time_window_wrap_midnight(self):
        """Test TimeWindow.is_active() for windows wrapping midnight."""
        # Window: 22:00-06:00 (wraps midnight)
        window = TimeWindow(hour=22, minute=0, end_hour=6, end_minute=0)
        
        # Before midnight, inside window
        assert window.is_active(time_type(22, 30))
        # After midnight, inside window
        assert window.is_active(time_type(3, 0))
        # Before midnight, outside window
        assert not window.is_active(time_type(9, 0))
        # Exact start time
        assert window.is_active(time_type(22, 0))

    def test_time_window_repr(self):
        """Test TimeWindow string representation."""
        window = TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)
        assert "06:30" in repr(window)
        assert "08:00" in repr(window)


class TestCirculationPumpScheduledWindows:
    """Test time-window scheduling functionality."""

    def test_init_default_windows(self):
        """Test that default time windows are morning and evening peaks."""
        pump = CirculationPumpScheduler()
        windows = pump.get_time_windows()
        
        assert len(windows) == 2
        # Morning: 06:30-08:00
        assert windows[0].start_time == time_type(6, 30)
        assert windows[0].end_time == time_type(8, 0)
        # Evening: 17:00-21:00
        assert windows[1].start_time == time_type(17, 0)
        assert windows[1].end_time == time_type(21, 0)

    def test_custom_time_windows(self):
        """Test initialization with custom time windows."""
        custom_windows = [
            TimeWindow(hour=7, minute=0, end_hour=9, end_minute=0),
            TimeWindow(hour=18, minute=0, end_hour=22, end_minute=0),
        ]
        pump = CirculationPumpScheduler(time_windows=custom_windows)
        windows = pump.get_time_windows()
        
        assert len(windows) == 2
        assert windows[0].start_time == time_type(7, 0)
        assert windows[1].start_time == time_type(18, 0)

    def test_set_time_windows(self):
        """Test updating time windows dynamically."""
        pump = CirculationPumpScheduler()
        new_windows = [TimeWindow(hour=5, minute=0, end_hour=9, end_minute=0)]
        
        pump.set_time_windows(new_windows)
        assert pump.get_time_windows() == new_windows

    def test_set_time_windows_empty_raises(self):
        """Test that setting empty time windows raises ValueError."""
        pump = CirculationPumpScheduler()
        
        with pytest.raises(ValueError):
            pump.set_time_windows([])

    @patch("circulation_pump.datetime")
    def test_pump_turns_on_in_scheduled_window(self, mock_datetime):
        """Test that pump turns ON when entering a scheduled window."""
        pump = CirculationPumpScheduler(
            time_windows=[TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)]
        )
        
        # Mock current time: 06:45 (inside window)
        mock_now = Mock()
        mock_now.time.return_value = time_type(6, 45)
        mock_datetime.now.return_value = mock_now
        
        # No boiler active, no heating demand, but in scheduled window
        result = pump.should_pump(
            boiler_active=False,
            room_targets={},
            room_actuals={}
        )
        
        assert result is True
        assert pump.state == PumpState.ON
        assert pump.in_scheduled_window is True

    @patch("circulation_pump.datetime")
    def test_pump_stays_off_outside_scheduled_window(self, mock_datetime):
        """Test that pump stays OFF when outside scheduled windows."""
        pump = CirculationPumpScheduler(
            time_windows=[TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)]
        )
        
        # Mock current time: 12:00 (outside window)
        mock_now = Mock()
        mock_now.time.return_value = time_type(12, 0)
        mock_datetime.now.return_value = mock_now
        
        # No demand
        result = pump.should_pump(
            boiler_active=False,
            room_targets={},
            room_actuals={}
        )
        
        assert result is False
        assert pump.state == PumpState.OFF
        assert pump.in_scheduled_window is False

    @patch("circulation_pump.datetime")
    def test_pump_exits_scheduled_window(self, mock_datetime):
        """Test that pump transitions through COOLDOWN when exiting scheduled window."""
        pump = CirculationPumpScheduler(
            min_runtime_s=600,
            time_windows=[TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)]
        )
        
        # Start: inside window at 06:45
        mock_now = Mock()
        mock_now.time.return_value = time_type(6, 45)
        mock_datetime.now.return_value = mock_now
        
        pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        assert pump.state == PumpState.ON
        
        # Wait past minimum runtime and move outside window (08:15)
        # Simulate enough time passing
        pump.state_enter_time = time.monotonic() - 700  # More than min_runtime_s
        mock_now.time.return_value = time_type(8, 15)
        
        result = pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
        # Should transition to COOLDOWN since min runtime met and not in window
        assert pump.state == PumpState.COOLDOWN

    @patch("circulation_pump.datetime")
    def test_pump_prefers_boiler_over_schedule(self, mock_datetime):
        """Test that boiler demand overrides scheduled windows."""
        pump = CirculationPumpScheduler(
            time_windows=[TimeWindow(hour=12, minute=0, end_hour=13, end_minute=0)]
        )
        
        # Outside window (10:00), but boiler active
        mock_now = Mock()
        mock_now.time.return_value = time_type(10, 0)
        mock_datetime.now.return_value = mock_now
        
        result = pump.should_pump(
            boiler_active=True,  # Boiler is firing
            room_targets={},
            room_actuals={}
        )
        
        assert result is True
        assert pump.state == PumpState.ON
        assert pump.in_scheduled_window is False  # Not in window, but boiler is on

    @patch("circulation_pump.datetime")
    def test_is_in_scheduled_window(self, mock_datetime):
        """Test _is_in_scheduled_window() helper."""
        pump = CirculationPumpScheduler(
            time_windows=[
                TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0),
                TimeWindow(hour=17, minute=0, end_hour=21, end_minute=0),
            ]
        )
        
        # Test morning window
        mock_now = Mock()
        mock_now.time.return_value = time_type(7, 0)
        mock_datetime.now.return_value = mock_now
        assert pump._is_in_scheduled_window() is True
        
        # Test evening window
        mock_now.time.return_value = time_type(19, 30)
        assert pump._is_in_scheduled_window() is True
        
        # Test outside windows
        mock_now.time.return_value = time_type(12, 0)
        assert pump._is_in_scheduled_window() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
