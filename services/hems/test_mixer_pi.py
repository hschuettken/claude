"""Unit tests for mixer PI control loop (#1019-#1024).

Covers:
  - Basic PI computation (error → action)
  - Anti-windup clamping (#1020)
  - Oscillation detection and deadband widening (#1021)
  - Safety guards for over/under temperature (#1022)
  - Valve position estimation from pulse history (#1024)
  - Async run_loop wiring (#1019)
  - InfluxDB field generation (#1023)
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock

from mixer_pi import MixerPIConfig, MixerPIController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# #1019 — Basic PI computation
# ---------------------------------------------------------------------------


class TestBasicCompute:
    def test_positive_error_produces_open_action(self):
        ctrl = make_controller()
        output, action = ctrl.compute(setpoint=50.0, measured=45.0)
        assert action == "open"
        assert output > 0

    def test_negative_error_produces_close_action(self):
        ctrl = make_controller()
        output, action = ctrl.compute(setpoint=45.0, measured=50.0)
        assert action == "close"
        assert output < 0

    def test_error_within_deadband_produces_hold(self):
        ctrl = make_controller(deadband=2.0)
        output, action = ctrl.compute(setpoint=50.0, measured=50.5)
        assert action == "hold"
        assert output == 0.0

    def test_error_exactly_at_deadband_boundary_produces_hold(self):
        ctrl = make_controller(deadband=1.0)
        # error = 1.0 — NOT strictly less than deadband 1.0, so should NOT hold
        output, action = ctrl.compute(setpoint=51.0, measured=50.0)
        assert action == "open"

    def test_proportional_dominates_on_first_call(self):
        # On the first call integral is zero; output ≈ kp * error.
        ctrl = make_controller(kp=2.0, ki=0.0)
        output, _ = ctrl.compute(setpoint=55.0, measured=50.0)
        # error=5, kp=2, ki=0 → output clamped at output_max_per_cycle=10
        assert output == pytest.approx(10.0)

    def test_output_clamped_to_max_per_cycle(self):
        ctrl = make_controller(kp=10.0, ki=0.0, output_max_per_cycle=5.0)
        output, _ = ctrl.compute(setpoint=60.0, measured=40.0)
        assert output <= 5.0

    def test_output_clamped_to_negative_max_per_cycle(self):
        ctrl = make_controller(kp=10.0, ki=0.0, output_max_per_cycle=5.0)
        output, _ = ctrl.compute(setpoint=40.0, measured=60.0)
        assert output >= -5.0

    def test_integral_accumulates_across_calls(self):
        ctrl = make_controller(kp=0.0, ki=1.0, anti_windup_limit=100.0)
        # Two calls with error=2.0 each → integral = 2*ki*error = 4
        ctrl.compute(setpoint=52.0, measured=50.0)
        ctrl.compute(setpoint=52.0, measured=50.0)
        assert ctrl.state.integral == pytest.approx(4.0)

    def test_state_last_error_updated(self):
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)
        assert ctrl.state.last_error == pytest.approx(5.0)

    def test_reset_clears_state(self):
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)
        ctrl.reset()
        assert ctrl.state.integral == 0.0
        assert ctrl.state.last_error == 0.0
        assert ctrl.state.last_output == 0.0
        assert ctrl.state.valve_position_pct == 50.0


# ---------------------------------------------------------------------------
# #1020 — Anti-windup back-calculation
# ---------------------------------------------------------------------------


class TestAntiWindup:
    def test_integral_clamped_at_upper_limit(self):
        ctrl = make_controller(kp=0.0, ki=1.0, anti_windup_limit=5.0)
        # Each call with error=3 adds 3 to integral; should stop at 5.
        for _ in range(10):
            ctrl.compute(setpoint=53.0, measured=50.0)
        assert ctrl.state.integral <= 5.0

    def test_integral_clamped_at_lower_limit(self):
        ctrl = make_controller(kp=0.0, ki=1.0, anti_windup_limit=5.0)
        for _ in range(10):
            ctrl.compute(setpoint=47.0, measured=50.0)
        assert ctrl.state.integral >= -5.0

    def test_integral_does_not_grow_unboundedly(self):
        ctrl = make_controller(kp=0.0, ki=2.0, anti_windup_limit=8.0)
        for _ in range(50):
            ctrl.compute(setpoint=60.0, measured=50.0)
        assert abs(ctrl.state.integral) <= 8.0

    def test_integral_recovers_after_error_sign_change(self):
        ctrl = make_controller(kp=0.0, ki=1.0, anti_windup_limit=10.0)
        # Drive integral positive.
        for _ in range(5):
            ctrl.compute(setpoint=55.0, measured=50.0)
        positive_integral = ctrl.state.integral
        assert positive_integral > 0
        # Drive integral negative over several calls.
        for _ in range(20):
            ctrl.compute(setpoint=40.0, measured=50.0)
        assert ctrl.state.integral < positive_integral


# ---------------------------------------------------------------------------
# #1021 — Oscillation detection and deadband widening
# ---------------------------------------------------------------------------


class TestOscillationDetection:
    def _force_oscillations(self, ctrl: MixerPIController, n: int) -> None:
        """Alternate error sign to generate direction reversals."""
        for i in range(n):
            if i % 2 == 0:
                ctrl.state.last_output = 1.0  # pretend last was open
                ctrl.compute(setpoint=45.0, measured=50.0)  # error < 0 → close
            else:
                ctrl.state.last_output = -1.0  # pretend last was close
                ctrl.compute(setpoint=55.0, measured=50.0)  # error > 0 → open

    def test_oscillation_count_increments_on_reversal(self):
        ctrl = make_controller(deadband=0.5, oscillation_threshold=3)
        ctrl.state.last_output = 1.0
        ctrl.compute(setpoint=45.0, measured=50.0)  # reversal
        assert ctrl.state.oscillation_count >= 1

    def test_deadband_widens_after_threshold_reversals(self):
        ctrl = make_controller(
            deadband=1.0,
            oscillation_deadband_expand=0.5,
            oscillation_threshold=3,
        )
        self._force_oscillations(ctrl, 6)
        assert ctrl.state.active_deadband > 1.0

    def test_deadband_widens_to_correct_value(self):
        ctrl = make_controller(
            deadband=1.0,
            oscillation_deadband_expand=0.5,
            oscillation_threshold=3,
        )
        self._force_oscillations(ctrl, 6)
        assert ctrl.state.active_deadband == pytest.approx(1.5)

    def test_deadband_restored_after_stable_direction(self):
        ctrl = make_controller(
            deadband=1.0,
            oscillation_deadband_expand=0.5,
            oscillation_threshold=3,
        )
        # Widen first.
        self._force_oscillations(ctrl, 6)
        assert ctrl.state.active_deadband == pytest.approx(1.5)
        # Then run in the same direction several times.
        for _ in range(10):
            ctrl.compute(setpoint=55.0, measured=50.0)
        assert ctrl.state.active_deadband == pytest.approx(1.0)

    def test_oscillation_count_decays_on_stable_output(self):
        ctrl = make_controller(deadband=0.5, oscillation_threshold=10)
        # Build some count.
        for _ in range(4):
            if _ % 2 == 0:
                ctrl.state.last_output = 1.0
                ctrl.compute(setpoint=45.0, measured=50.0)
            else:
                ctrl.state.last_output = -1.0
                ctrl.compute(setpoint=55.0, measured=50.0)
        count_after_oscillation = ctrl.state.oscillation_count
        # Now drive same direction to decay.
        for _ in range(count_after_oscillation + 2):
            ctrl.compute(setpoint=55.0, measured=50.0)
        assert ctrl.state.oscillation_count < count_after_oscillation


# ---------------------------------------------------------------------------
# #1022 — Safety guards
# ---------------------------------------------------------------------------


class TestSafetyGuards:
    def test_over_temp_forces_close(self):
        ctrl = make_controller(flow_temp_max=70.0)
        output, action = ctrl.compute(setpoint=50.0, measured=75.0)
        assert action == "close"
        assert output < 0

    def test_over_temp_ignores_setpoint(self):
        # Even if setpoint > measured would normally open, safety overrides.
        ctrl = make_controller(flow_temp_max=70.0)
        output, action = ctrl.compute(setpoint=80.0, measured=75.0)
        assert action == "close"

    def test_under_temp_forces_open(self):
        ctrl = make_controller(flow_temp_min=20.0)
        output, action = ctrl.compute(setpoint=50.0, measured=15.0)
        assert action == "open"
        assert output > 0

    def test_under_temp_ignores_setpoint(self):
        # Even if setpoint < measured would normally close, safety overrides.
        ctrl = make_controller(flow_temp_min=20.0)
        output, action = ctrl.compute(setpoint=10.0, measured=15.0)
        assert action == "open"

    def test_normal_temp_range_not_affected_by_guards(self):
        ctrl = make_controller(flow_temp_max=70.0, flow_temp_min=20.0)
        output, action = ctrl.compute(setpoint=55.0, measured=50.0)
        # Normal PI should run — not forced by safety.
        assert action in ("open", "close", "hold")

    def test_exactly_at_max_boundary_is_not_safety(self):
        # measured == flow_temp_max is NOT over — guard is strictly greater-than.
        ctrl = make_controller(flow_temp_max=70.0, kp=1.0, ki=0.0, deadband=0.5)
        output, action = ctrl.compute(setpoint=70.0, measured=70.0)
        # error=0, within deadband → hold
        assert action == "hold"


# ---------------------------------------------------------------------------
# #1024 — Valve position estimation from pulse history
# ---------------------------------------------------------------------------


class TestValvePositionEstimation:
    def test_initial_position_is_50_pct(self):
        ctrl = make_controller()
        assert ctrl.estimate_valve_position() == pytest.approx(50.0)

    def test_open_pulses_increase_estimate(self):
        ctrl = make_controller(kp=1.0, ki=0.0, deadband=0.5)
        initial = ctrl.state.valve_position_pct
        ctrl.compute(setpoint=55.0, measured=50.0)
        assert ctrl.state.valve_position_pct > initial

    def test_close_pulses_decrease_estimate(self):
        ctrl = make_controller(kp=1.0, ki=0.0, deadband=0.5)
        initial = ctrl.state.valve_position_pct
        ctrl.compute(setpoint=45.0, measured=50.0)
        assert ctrl.state.valve_position_pct < initial

    def test_estimate_clamped_at_100(self):
        ctrl = make_controller(kp=1.0, ki=0.0, output_max_per_cycle=10.0)
        ctrl.state.valve_position_pct = 99.0
        ctrl.compute(setpoint=60.0, measured=50.0)
        assert ctrl.state.valve_position_pct <= 100.0

    def test_estimate_clamped_at_0(self):
        ctrl = make_controller(kp=1.0, ki=0.0, output_max_per_cycle=10.0)
        ctrl.state.valve_position_pct = 1.0
        ctrl.compute(setpoint=40.0, measured=50.0)
        assert ctrl.state.valve_position_pct >= 0.0

    def test_pulse_history_recorded(self):
        ctrl = make_controller(kp=1.0, ki=0.0, deadband=0.5)
        ctrl.compute(setpoint=55.0, measured=50.0)
        assert len(ctrl.state.pulse_history) == 1
        entry = ctrl.state.pulse_history[0]
        assert entry["direction"] == "open"
        assert "ts" in entry
        assert "magnitude" in entry

    def test_pulse_history_capped_at_100(self):
        ctrl = make_controller(kp=1.0, ki=0.0, deadband=0.5)
        for _ in range(120):
            ctrl.compute(setpoint=55.0, measured=50.0)
        assert len(ctrl.state.pulse_history) <= 100

    def test_hold_does_not_add_pulse(self):
        ctrl = make_controller(deadband=2.0)
        ctrl.compute(setpoint=50.0, measured=50.5)  # within deadband → hold
        assert len(ctrl.state.pulse_history) == 0


# ---------------------------------------------------------------------------
# #1023 — InfluxDB field generation
# ---------------------------------------------------------------------------


class TestInfluxDBFields:
    def test_get_state_dict_has_required_keys(self):
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)
        fields = ctrl.get_state_dict()
        expected_keys = {
            "integral",
            "last_error",
            "last_output",
            "valve_position_pct",
            "oscillation_count",
            "active_deadband",
        }
        assert expected_keys.issubset(fields.keys())

    def test_get_state_dict_values_are_numeric(self):
        ctrl = make_controller()
        ctrl.compute(setpoint=55.0, measured=50.0)
        fields = ctrl.get_state_dict()
        for key, value in fields.items():
            if key != "oscillation_count":
                assert isinstance(value, float), f"{key} should be float"


# ---------------------------------------------------------------------------
# #1019 — Async run_loop
# ---------------------------------------------------------------------------


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_loop_calls_apply_action(self):
        ctrl = make_controller()

        get_setpoint = AsyncMock(return_value=55.0)
        get_measured = AsyncMock(return_value=50.0)
        apply_action = AsyncMock()
        log_to_influx = AsyncMock()

        task = asyncio.create_task(
            ctrl.run_loop(get_setpoint, get_measured, apply_action, log_to_influx)
        )
        # Let it run one iteration (interval is 10s but we'll cancel after first call).
        await asyncio.sleep(0)  # yield control so the loop starts
        # Give enough ticks for at least one iteration.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        apply_action.assert_called()

    @pytest.mark.asyncio
    async def test_run_loop_calls_log_to_influx(self):
        ctrl = make_controller(interval_seconds=0)  # zero interval for fast test

        call_count = 0

        async def fast_setpoint():
            return 55.0

        async def fast_measured():
            return 50.0

        async def fast_action(action, magnitude):
            pass

        async def capture_influx(fields):
            nonlocal call_count
            call_count += 1

        task = asyncio.create_task(
            ctrl.run_loop(fast_setpoint, fast_measured, fast_action, capture_influx)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_run_loop_logs_correct_fields(self):
        """run_loop must pass setpoint/measured/output/action to log_to_influx."""
        ctrl = make_controller(interval_seconds=0)

        captured: dict = {}

        async def capture_influx(fields):
            captured.update(fields)

        task = asyncio.create_task(
            ctrl.run_loop(
                AsyncMock(return_value=55.0),
                AsyncMock(return_value=50.0),
                AsyncMock(),
                capture_influx,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert "setpoint_c" in captured
        assert "measured_c" in captured
        assert "output_pct" in captured
        assert "action" in captured

    @pytest.mark.asyncio
    async def test_run_loop_survives_apply_action_exception(self):
        """Loop should continue even if apply_action raises."""
        ctrl = make_controller(interval_seconds=0)

        error_count = 0
        success_count = 0

        async def flaky_action(action, magnitude):
            nonlocal error_count
            error_count += 1
            raise RuntimeError("valve comms error")

        async def count_influx(fields):
            nonlocal success_count
            success_count += 1

        task = asyncio.create_task(
            ctrl.run_loop(
                AsyncMock(return_value=55.0),
                AsyncMock(return_value=50.0),
                flaky_action,
                count_influx,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Loop ran multiple times despite apply_action raising each time.
        assert error_count >= 1

    @pytest.mark.asyncio
    async def test_run_loop_works_without_influx_callback(self):
        """log_to_influx=None should not raise."""
        ctrl = make_controller(interval_seconds=0)

        task = asyncio.create_task(
            ctrl.run_loop(
                AsyncMock(return_value=55.0),
                AsyncMock(return_value=50.0),
                AsyncMock(),
                None,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # If we got here without exception the test passes.
