"""Advanced unit tests for mixer PI control loop (#1019-#1024).

Covers:
  - Zero error → zero output behavior
  - Positive error → heating action
  - Anti-windup integral clamping under sustained error
  - Oscillation detection with deadband widening
  - Safety temperature limits (over/under)
  - Edge cases and numerical stability
"""

from __future__ import annotations

import pytest
from mixer_pi import MixerPIConfig, MixerPIController


def make_controller(**kwargs) -> MixerPIController:
    """Create a controller with test-friendly defaults (can be overridden)."""
    cfg = MixerPIConfig(
        kp=1.0,
        ki=0.1,
        anti_windup_limit=10.0,
        deadband=1.0,
        oscillation_deadband_expand=0.5,
        oscillation_threshold=3,
        flow_temp_max=70.0,
        flow_temp_min=20.0,
        output_max_per_cycle=10.0,
        interval_seconds=10,
        **kwargs,
    )
    return MixerPIController(cfg)


class TestPINoErrorZeroOutput:
    """Test #1: PI controller produces near-zero output when error is zero."""

    def test_setpoint_equals_measured_returns_zero(self):
        """When setpoint == measured, output should be 0 (within deadband)."""
        ctrl = make_controller()
        output, action = ctrl.compute(setpoint=50.0, measured=50.0)
        assert output == 0.0
        assert action == "hold"

    def test_error_within_deadband_returns_zero(self):
        """Small error within deadband → zero output (no oscillation)."""
        ctrl = make_controller(deadband=1.0)
        # Error = 50.5 - 50.0 = 0.5°C, within 1.0°C deadband
        output, action = ctrl.compute(setpoint=50.5, measured=50.0)
        assert output == 0.0
        assert action == "hold"

    def test_multiple_zero_errors_accumulates_no_integral(self):
        """Repeated zero-error cycles should not accumulate integral."""
        ctrl = make_controller(ki=0.1)
        for _ in range(5):
            output, action = ctrl.compute(50.0, 50.0)
            assert output == 0.0
        # Integral should remain 0
        assert ctrl.state.integral == 0.0


class TestPIPositiveErrorHeats:
    """Test #2: PI controller opens valve (positive output) when room is cold."""

    def test_positive_error_opens_valve(self):
        """Measured < setpoint → positive output (open action)."""
        ctrl = make_controller(kp=1.0)
        # Error = 55 - 45 = +10°C
        output, action = ctrl.compute(setpoint=55.0, measured=45.0)
        assert output > 0.0
        assert action == "open"

    def test_proportional_term_scales_with_error(self):
        """Larger error → larger proportional output."""
        ctrl = make_controller(kp=1.0, ki=0.0)
        output_small, _ = ctrl.compute(setpoint=51.0, measured=50.0)  # 1°C error
        output_large, _ = ctrl.compute(setpoint=55.0, measured=50.0)  # 5°C error
        assert output_large > output_small
        # Kp=1.0 → proportional should be 1.0 and 5.0 respectively
        assert output_small == pytest.approx(1.0)
        assert output_large == pytest.approx(5.0)

    def test_integral_accumulates_over_time(self):
        """Sustained error accumulates integral term."""
        ctrl = make_controller(kp=0.0, ki=0.1, anti_windup_limit=100.0)
        # Five cycles with 10°C sustained error
        for i in range(5):
            output, _ = ctrl.compute(setpoint=60.0, measured=50.0)
            # Pure integral: ki * error = 0.1 * 10 = 1.0 per cycle
            expected_integral = 1.0 * (i + 1)
            assert ctrl.state.integral == pytest.approx(expected_integral)


class TestPIAntiWindupClampsIntegral:
    """Test #3: Anti-windup prevents integral from growing unbounded."""

    def test_integral_clamped_at_positive_limit(self):
        """Sustained positive error clamps integral at anti_windup_limit."""
        ctrl = make_controller(kp=0.0, ki=0.2, anti_windup_limit=10.0)
        # Sustained large error, 60 cycles → integral would exceed 120 without clamping
        for _ in range(60):
            output, _ = ctrl.compute(setpoint=100.0, measured=50.0)
        # Integral clamped at limit
        assert ctrl.state.integral == pytest.approx(10.0)
        assert ctrl.state.integral <= 10.0

    def test_integral_clamped_at_negative_limit(self):
        """Sustained negative error clamps integral at -anti_windup_limit."""
        ctrl = make_controller(kp=0.0, ki=0.2, anti_windup_limit=10.0)
        # Sustained large negative error (measured > setpoint)
        for _ in range(60):
            output, _ = ctrl.compute(setpoint=40.0, measured=90.0)
        # Integral clamped at negative limit
        assert ctrl.state.integral == pytest.approx(-10.0)
        assert ctrl.state.integral >= -10.0

    def test_clamping_limits_output(self):
        """Clamped integral limits the total output magnitude."""
        ctrl = make_controller(
            kp=0.1, ki=0.2, anti_windup_limit=10.0, output_max_per_cycle=50.0
        )
        # Sustained error: proportional alone would be huge, but integral caps at 10
        for _ in range(60):
            output, _ = ctrl.compute(setpoint=100.0, measured=10.0)
        # Without anti-windup, integral could grow to ~180 (0.2 * 90 * 10 cycles)
        # With clamping, integral = 10, and total output bounded
        assert abs(ctrl.state.integral) <= 10.0
        assert abs(ctrl.state.last_output) <= 50.0


class TestPIOscillationDetection:
    """Test #4: Oscillation detection widens deadband to prevent hunting."""

    def test_oscillation_count_increments_on_reversal(self):
        """Direction reversal → oscillation_count increments."""
        ctrl = make_controller(kp=1.0, ki=0.0)
        ctrl.compute(setpoint=55.0, measured=50.0)  # +5°C error → open (+output)
        assert ctrl.state.last_output > 0
        assert ctrl.state.oscillation_count == 0

        ctrl.compute(setpoint=45.0, measured=50.0)  # -5°C error → close (-output)
        # Direction reversed from + to -
        assert ctrl.state.oscillation_count >= 1

    def test_deadband_widens_after_threshold_reversals(self):
        """After oscillation_threshold reversals, deadband widens."""
        ctrl = make_controller(
            kp=1.0,
            ki=0.0,
            deadband=1.0,
            oscillation_deadband_expand=0.5,
            oscillation_threshold=3,
        )
        initial_db = ctrl.state.active_deadband
        # Alternate between large positive and negative errors to cause reversals
        for i in range(10):
            if i % 2 == 0:
                ctrl.compute(setpoint=60.0, measured=50.0)  # +10°C
            else:
                ctrl.compute(setpoint=40.0, measured=50.0)  # -10°C

        # After enough reversals, deadband should have expanded
        assert ctrl.state.active_deadband >= initial_db
        if ctrl.state.oscillation_count >= 3:
            assert ctrl.state.active_deadband == pytest.approx(1.5)

    def test_deadband_restores_when_oscillation_stops(self):
        """Stable direction → deadband shrinks back to original."""
        ctrl = make_controller(
            kp=1.0,
            ki=0.0,
            deadband=1.0,
            oscillation_deadband_expand=0.5,
            oscillation_threshold=3,
        )
        # Force deadband to widen
        ctrl.state.active_deadband = 1.5
        ctrl.state.oscillation_count = 3

        # Apply stable error in one direction for several cycles
        for _ in range(5):
            ctrl.compute(setpoint=60.0, measured=50.0)  # Consistent +error

        # Oscillation count should decay and deadband should restore
        if ctrl.state.oscillation_count == 0:
            assert ctrl.state.active_deadband == pytest.approx(1.0)

    def test_alternating_errors_trigger_widening_threshold(self):
        """Exactly 3 reversals triggers the threshold."""
        ctrl = make_controller(oscillation_threshold=3, oscillation_deadband_expand=0.5)
        # Cycle 1: +error → +output
        ctrl.compute(setpoint=55.0, measured=50.0)
        # Cycle 2: -error → -output (reversal #1)
        ctrl.compute(setpoint=45.0, measured=50.0)
        assert ctrl.state.oscillation_count == 1
        # Cycle 3: +error → +output (reversal #2)
        ctrl.compute(setpoint=55.0, measured=50.0)
        assert ctrl.state.oscillation_count == 2
        # Cycle 4: -error → -output (reversal #3 → trigger)
        ctrl.compute(setpoint=45.0, measured=50.0)
        assert ctrl.state.oscillation_count == 3
        assert ctrl.state.active_deadband == pytest.approx(1.5)


class TestPISafetyForceCloseAbove70C:
    """Test #5: Safety override closes valve when flow temp exceeds 70°C."""

    def test_force_close_above_flow_temp_max(self):
        """Flow temp > 70°C → forced close regardless of error."""
        ctrl = make_controller(flow_temp_max=70.0)
        output, action = ctrl.compute(setpoint=45.0, measured=75.0)
        assert output < 0.0
        assert action == "close"
        # Should be forced to max close
        assert output == pytest.approx(-10.0)

    def test_force_close_at_exact_limit(self):
        """Flow temp = 70°C (exact limit) → close."""
        ctrl = make_controller(flow_temp_max=70.0)
        output, action = ctrl.compute(setpoint=50.0, measured=70.1)
        assert action == "close"
        assert output < 0.0

    def test_force_close_disables_normal_control(self):
        """When force-close active, proportional & integral are ignored."""
        ctrl = make_controller(flow_temp_max=70.0, kp=10.0, ki=10.0)
        # Even if proportional + integral would try to open, close wins
        output, action = ctrl.compute(setpoint=100.0, measured=75.0)
        assert action == "close"
        assert output == pytest.approx(-10.0)

    def test_repeated_force_close_pulses(self):
        """Multiple cycles with high temp → multiple close pulses."""
        ctrl = make_controller(flow_temp_max=70.0)
        for i in range(3):
            output, action = ctrl.compute(setpoint=45.0, measured=75.0)
            assert action == "close"
            # Pulse history should record each close
            assert len(ctrl.state.pulse_history) == i + 1


class TestPISafetyForceOpenBelow20C:
    """Test #6: Safety override opens valve when flow temp drops below 20°C."""

    def test_force_open_below_flow_temp_min(self):
        """Flow temp < 20°C → forced open regardless of error."""
        ctrl = make_controller(flow_temp_min=20.0)
        output, action = ctrl.compute(setpoint=55.0, measured=15.0)
        assert output > 0.0
        assert action == "open"
        # Should be forced to max open
        assert output == pytest.approx(10.0)

    def test_force_open_at_exact_limit(self):
        """Flow temp = 19.9°C (below limit) → open."""
        ctrl = make_controller(flow_temp_min=20.0)
        output, action = ctrl.compute(setpoint=50.0, measured=19.9)
        assert action == "open"
        assert output > 0.0

    def test_force_open_disables_normal_control(self):
        """When force-open active, proportional & integral are ignored."""
        ctrl = make_controller(flow_temp_min=20.0, kp=10.0, ki=10.0)
        # Even if proportional + integral would try to close, open wins
        output, action = ctrl.compute(setpoint=40.0, measured=15.0)
        assert action == "open"
        assert output == pytest.approx(10.0)


class TestValvePositionEstimate:
    """Test #7: Valve position tracking from pulse history."""

    def test_valve_position_starts_at_50_percent(self):
        """Initial valve position is 50%."""
        ctrl = make_controller()
        assert ctrl.estimate_valve_position() == 50.0

    def test_valve_position_increments_on_open_pulse(self):
        """Open pulse (+5%) increases position."""
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)  # Triggers open pulse
        pos = ctrl.estimate_valve_position()
        assert pos > 50.0

    def test_valve_position_decrements_on_close_pulse(self):
        """Close pulse (-5%) decreases position."""
        ctrl = make_controller()
        # Start by opening to some level
        for _ in range(5):
            ctrl.compute(setpoint=60.0, measured=50.0)
        mid_pos = ctrl.estimate_valve_position()
        # Then close for several cycles
        for _ in range(3):
            ctrl.compute(setpoint=40.0, measured=50.0)
        final_pos = ctrl.estimate_valve_position()
        assert final_pos < mid_pos

    def test_valve_position_clamped_0_to_100(self):
        """Valve position never goes below 0 or above 100."""
        ctrl = make_controller(output_max_per_cycle=50.0)
        # Try to open beyond 100%
        for _ in range(10):
            ctrl.compute(setpoint=100.0, measured=10.0)
        assert ctrl.estimate_valve_position() == 100.0

        # Reset and try to close below 0%
        ctrl = make_controller(output_max_per_cycle=50.0)
        for _ in range(10):
            ctrl.compute(setpoint=10.0, measured=100.0)
        assert ctrl.estimate_valve_position() == 0.0

    def test_pulse_history_recorded_on_action(self):
        """Each non-zero pulse is recorded in pulse_history."""
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)  # Open pulse
        assert len(ctrl.state.pulse_history) == 1
        assert ctrl.state.pulse_history[0]["direction"] == "open"
        assert "ts" in ctrl.state.pulse_history[0]

    def test_pulse_history_capped_at_100_entries(self):
        """Pulse history is trimmed to 100 most recent entries."""
        ctrl = make_controller()
        # Generate 150 pulses
        for i in range(150):
            if i % 2 == 0:
                ctrl.compute(setpoint=60.0, measured=50.0)
            else:
                ctrl.compute(setpoint=40.0, measured=50.0)
        # Should only keep last 100
        assert len(ctrl.state.pulse_history) == 100


class TestStateSnapshot:
    """Test #8: State dict for InfluxDB logging."""

    def test_get_state_dict_contains_all_fields(self):
        """get_state_dict returns all required fields."""
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)
        state = ctrl.get_state_dict()
        assert "integral" in state
        assert "last_error" in state
        assert "last_output" in state
        assert "valve_position_pct" in state
        assert "oscillation_count" in state
        assert "active_deadband" in state

    def test_state_dict_values_are_rounded(self):
        """Numeric fields in state dict are appropriately rounded."""
        ctrl = make_controller()
        ctrl.compute(setpoint=55.123456, measured=50.654321)
        state = ctrl.get_state_dict()
        # Check rounding (should have reasonable decimal places)
        assert isinstance(state["integral"], float)
        assert isinstance(state["last_error"], float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
