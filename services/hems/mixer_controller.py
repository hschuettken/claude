"""PI controller for mixing valve (thermostatic load balancing).

Implements a proportional-integral (PI) controller with anti-windup and rate limiting
to control the mixing valve position based on setpoint vs measured flow temperature.

Typical use:
  controller = MixerController(kp=3.0, ki=0.15, max_integral=20, rate_limit=2.0)
  valve_pos = controller.compute(setpoint_c=50, measured_c=48, dt_s=10)
  # valve_pos is 0–100 (%)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("hems.mixer_controller")


@dataclass
class MixerController:
    """PI controller for mixing valve position.

    Attributes:
        kp: Proportional gain (default 3.0)
        ki: Integral gain (default 0.15)
        max_integral: Max integral term clamping (default 20)
        rate_limit: Max % valve position change per call (default 2.0)
    """

    kp: float = 3.0
    ki: float = 0.15
    max_integral: float = 20.0
    rate_limit: float = 2.0

    # State (persisted across calls)
    last_error: float = 0.0
    integral: float = 0.0
    last_output: float = 0.0

    def compute(self, setpoint_c: float, measured_c: float, dt_s: float) -> float:
        """Compute valve position based on error and time delta.

        Args:
            setpoint_c: Target flow temperature (°C)
            measured_c: Current measured flow temperature (°C)
            dt_s: Time delta since last call (seconds)

        Returns:
            Valve position: 0–100 (%)
        """
        # Calculate error
        error = setpoint_c - measured_c

        # Update integral (accumulate error over time)
        self.integral += error * dt_s

        # Anti-windup: clamp integral when output would saturate
        # Rough estimate: output = kp*error + ki*integral
        # If output would exceed [0, 100], clamp integral
        output_no_windup = self.kp * error + self.ki * self.integral
        if output_no_windup > 100:
            self.integral = (100 - self.kp * error) / self.ki if self.ki != 0 else 0
        elif output_no_windup < 0:
            self.integral = (0 - self.kp * error) / self.ki if self.ki != 0 else 0

        # Also clamp integral independently
        self.integral = max(-self.max_integral, min(self.max_integral, self.integral))

        # Compute PI output
        proportional = self.kp * error
        integral_term = self.ki * self.integral
        raw_output = proportional + integral_term

        # Clamp to [0, 100]
        raw_output = max(0.0, min(100.0, raw_output))

        # Rate limiting: valve can't move more than rate_limit % per call
        if self.last_output is not None:
            max_change = self.rate_limit
            if raw_output > self.last_output + max_change:
                raw_output = self.last_output + max_change
            elif raw_output < self.last_output - max_change:
                raw_output = self.last_output - max_change

        self.last_output = raw_output
        self.last_error = error

        logger.debug(
            "MixerController.compute: error=%.2f, integral=%.2f, output=%.2f%%",
            error,
            self.integral,
            raw_output,
        )

        return round(raw_output, 2)

    def reset(self) -> None:
        """Reset controller state (zero integral, last error, output)."""
        self.integral = 0.0
        self.last_error = 0.0
        self.last_output = 0.0
        logger.info("MixerController reset")
