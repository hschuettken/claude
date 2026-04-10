"""Mixer PI Control Loop (#1019-#1024).

10-second interval PI controller for heating circuit mixer valve.
Controls flow temperature by adjusting valve position via open/close pulses.

Features:
  #1019 — 10-second interval async PI control loop
  #1020 — Anti-windup via back-calculation
  #1021 — Oscillation detection with deadband widening
  #1022 — Safety guards for flow temp excursions
  #1023 — InfluxDB logging to measurement hems.mixer_control
  #1024 — Valve position estimate from cumulative pulse history
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("hems.mixer_pi")


@dataclass
class MixerPIConfig:
    """Tuning and safety parameters for the mixer PI controller."""

    kp: float = 0.8
    """Proportional gain."""

    ki: float = 0.05
    """Integral gain (per-iteration accumulation, not per-second)."""

    anti_windup_limit: float = 50.0
    """Clamp on the integral accumulator (prevents wind-up into saturation)."""

    deadband: float = 1.0
    """°C deadband around setpoint — no action taken within this band."""

    oscillation_deadband_expand: float = 0.5
    """Additional °C added to deadband when oscillation is detected."""

    oscillation_threshold: int = 3
    """Number of consecutive direction reversals that trigger deadband widening."""

    flow_temp_max: float = 70.0
    """Safety ceiling: if measured flow temp exceeds this, force close. °C"""

    flow_temp_min: float = 20.0
    """Safety floor: if measured flow temp drops below this, force open. °C"""

    output_max_per_cycle: float = 10.0
    """Maximum valve position change per cycle (%). Limits slew rate."""

    interval_seconds: int = 10
    """Control loop period in seconds (#1019)."""


@dataclass
class MixerPIState:
    """Mutable runtime state for the mixer PI controller."""

    integral: float = 0.0
    last_error: float = 0.0
    last_output: float = 0.0
    valve_position_pct: float = 50.0
    """Estimated valve position 0-100 (%) derived from pulse history (#1024)."""

    pulse_history: list = field(default_factory=list)
    """List of pulse dicts: {ts, direction, magnitude}. Capped at 100 entries (#1024)."""

    oscillation_count: int = 0
    """Rolling count of direction reversals."""

    active_deadband: float = 1.0
    """Current deadband in °C — may be widened by oscillation detection (#1021)."""


class MixerPIController:
    """PI controller for heating circuit mixer valve.

    Adjusts valve position to maintain target flow temperature.
    Anti-windup via back-calculation (#1020).
    Oscillation detection with deadband widening (#1021).
    Safety guards for flow temp excursions (#1022).
    Valve position estimated from cumulative pulse history (#1024).
    """

    def __init__(self, config: Optional[MixerPIConfig] = None) -> None:
        self.config = config or MixerPIConfig()
        self.state = MixerPIState(active_deadband=self.config.deadband)

    # ------------------------------------------------------------------
    # Core compute
    # ------------------------------------------------------------------

    def compute(self, setpoint: float, measured: float) -> tuple[float, str]:
        """Compute PI output for one cycle.

        Args:
            setpoint: Target flow temperature (°C).
            measured: Current measured flow temperature (°C).

        Returns:
            (output_pct_change, action) where:
              - output_pct_change is a signed percentage change to apply to valve
                position (positive = open, negative = close).
              - action is 'open' | 'close' | 'hold'.
        """
        # #1022 — Safety guards take priority over normal control.
        if measured > self.config.flow_temp_max:
            logger.warning(
                "Flow temp %.1f°C exceeds safety max %.1f°C — forcing close",
                measured,
                self.config.flow_temp_max,
            )
            output = -self.config.output_max_per_cycle
            self._record_pulse(output)
            return output, "close"

        if measured < self.config.flow_temp_min:
            logger.warning(
                "Flow temp %.1f°C below safety min %.1f°C — forcing open",
                measured,
                self.config.flow_temp_min,
            )
            output = self.config.output_max_per_cycle
            self._record_pulse(output)
            return output, "open"

        error = setpoint - measured

        # #1021 — Use potentially widened deadband.
        if abs(error) < self.state.active_deadband:
            logger.debug(
                "Error %.2f°C within deadband %.2f°C — hold",
                error,
                self.state.active_deadband,
            )
            return 0.0, "hold"

        # Proportional term.
        proportional = self.config.kp * error

        # #1020 — Integral with back-calculation anti-windup.
        # Accumulate raw, then clamp; the clamped value is what is used.
        raw_integral = self.state.integral + self.config.ki * error
        clamped_integral = max(
            -self.config.anti_windup_limit,
            min(self.config.anti_windup_limit, raw_integral),
        )
        self.state.integral = clamped_integral

        raw_output = proportional + clamped_integral

        # Clamp per-cycle slew rate.
        output = max(
            -self.config.output_max_per_cycle,
            min(self.config.output_max_per_cycle, raw_output),
        )

        # #1021 — Oscillation detection: count direction reversals.
        self._update_oscillation(output)

        self.state.last_error = error
        self.state.last_output = output
        self._record_pulse(output)

        action = "open" if output > 0 else "close"
        logger.debug(
            "PI: sp=%.1f meas=%.1f err=%.2f P=%.2f I=%.2f out=%.2f action=%s",
            setpoint,
            measured,
            error,
            proportional,
            clamped_integral,
            output,
            action,
        )
        return output, action

    # ------------------------------------------------------------------
    # Oscillation detection (#1021)
    # ------------------------------------------------------------------

    def _update_oscillation(self, output: float) -> None:
        """Detect direction reversals and widen deadband if oscillating."""
        if self.state.last_output == 0.0:
            return

        direction_changed = (output > 0) != (self.state.last_output > 0)

        if direction_changed:
            self.state.oscillation_count += 1
            if self.state.oscillation_count >= self.config.oscillation_threshold:
                new_db = self.config.deadband + self.config.oscillation_deadband_expand
                if self.state.active_deadband < new_db:
                    self.state.active_deadband = new_db
                    logger.info(
                        "Oscillation detected (%d reversals) — deadband widened to %.2f°C",
                        self.state.oscillation_count,
                        self.state.active_deadband,
                    )
        else:
            # Decay oscillation count when direction is stable.
            self.state.oscillation_count = max(0, self.state.oscillation_count - 1)
            if (
                self.state.oscillation_count == 0
                and self.state.active_deadband > self.config.deadband
            ):
                self.state.active_deadband = self.config.deadband
                logger.info(
                    "Oscillation resolved — deadband restored to %.2f°C",
                    self.state.active_deadband,
                )

    # ------------------------------------------------------------------
    # Valve position estimate (#1024)
    # ------------------------------------------------------------------

    def _record_pulse(self, output_pct: float) -> None:
        """Record a valve pulse and update cumulative position estimate (#1024)."""
        self.state.valve_position_pct = max(
            0.0, min(100.0, self.state.valve_position_pct + output_pct)
        )
        if output_pct == 0.0:
            return

        self.state.pulse_history.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "direction": "open" if output_pct > 0 else "close",
                "magnitude": round(abs(output_pct), 3),
            }
        )
        # Keep last 100 pulses to bound memory usage.
        if len(self.state.pulse_history) > 100:
            self.state.pulse_history = self.state.pulse_history[-100:]

    def estimate_valve_position(self) -> float:
        """Return estimated valve position (0-100 %) from pulse history (#1024)."""
        return round(self.state.valve_position_pct, 2)

    # ------------------------------------------------------------------
    # State snapshot for InfluxDB (#1023)
    # ------------------------------------------------------------------

    def get_state_dict(self) -> dict:
        """Return controller state fields suitable for InfluxDB logging (#1023)."""
        return {
            "integral": round(self.state.integral, 4),
            "last_error": round(self.state.last_error, 4),
            "last_output": round(self.state.last_output, 4),
            "valve_position_pct": round(self.state.valve_position_pct, 2),
            "oscillation_count": self.state.oscillation_count,
            "active_deadband": round(self.state.active_deadband, 4),
        }

    # ------------------------------------------------------------------
    # Async control loop (#1019)
    # ------------------------------------------------------------------

    async def run_loop(
        self,
        get_setpoint: Callable,
        get_measured: Callable,
        apply_action: Callable,
        log_to_influx: Optional[Callable] = None,
    ) -> None:
        """Run the 10-second PI control loop (#1019).

        Runs indefinitely until the enclosing task is cancelled.

        Args:
            get_setpoint:   async fn() -> float — current target flow temperature.
            get_measured:   async fn() -> float — current measured flow temperature.
            apply_action:   async fn(action: str, magnitude: float) -> None
                            Called with ('open'|'close'|'hold', abs(output_pct)).
            log_to_influx:  optional async fn(fields: dict) -> None
                            Receives measurement fields for hems.mixer_control (#1023).
        """
        logger.info(
            "Mixer PI loop starting (interval=%ds, kp=%.2f, ki=%.3f)",
            self.config.interval_seconds,
            self.config.kp,
            self.config.ki,
        )

        while True:
            try:
                setpoint = await get_setpoint()
                measured = await get_measured()

                output, action = self.compute(setpoint, measured)
                await apply_action(action, abs(output))

                # #1023 — Log to InfluxDB measurement hems.mixer_control.
                if log_to_influx is not None:
                    fields = self.get_state_dict()
                    fields.update(
                        {
                            "setpoint_c": round(setpoint, 2),
                            "measured_c": round(measured, 2),
                            "output_pct": round(output, 4),
                            "action": action,
                        }
                    )
                    try:
                        await log_to_influx(fields)
                    except Exception as exc:
                        logger.warning(
                            "Failed to log mixer PI state to InfluxDB: %s", exc
                        )

            except asyncio.CancelledError:
                logger.info("Mixer PI loop cancelled")
                raise
            except Exception as exc:
                logger.error("Mixer PI loop error: %s", exc, exc_info=True)

            await asyncio.sleep(self.config.interval_seconds)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset controller state to defaults."""
        self.state = MixerPIState(active_deadband=self.config.deadband)
        logger.info("MixerPIController reset")
