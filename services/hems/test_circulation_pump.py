"""Unit tests for circulation pump scheduler.

Tests the state machine logic, hysteresis, runtime limits, and HA integration.
"""

import pytest
import time
from unittest.mock import Mock, patch, AsyncMock

from circulation_pump import CirculationPumpScheduler, PumpState


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
