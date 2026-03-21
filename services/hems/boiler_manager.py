"""Boiler burner state machine with short-cycle protection.

Prevents rapid on/off cycling by enforcing minimum ON and OFF times.
Logs all state transitions.

Typical use:
  manager = BoilerManager(min_off_time_s=600, min_on_time_s=300)
  should_fire = manager.should_fire(demand_w=15000)
  # Transitions: IDLE → HEATING → COOLDOWN → IDLE
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("hems.boiler_manager")


class BoilerState(str, Enum):
    """Boiler burner states."""

    IDLE = "idle"
    HEATING = "heating"
    COOLDOWN = "cooldown"


class BoilerManager:
    """Anti-short-cycle boiler burner manager.

    Attributes:
        min_off_time_s: Minimum burner OFF duration (default 600 = 10 min)
        min_on_time_s: Minimum burner ON duration (default 300 = 5 min)
    """

    def __init__(self, min_off_time_s: float = 600.0, min_on_time_s: float = 300.0):
        self.min_off_time_s = min_off_time_s
        self.min_on_time_s = min_on_time_s

        self.state = BoilerState.IDLE
        self.state_enter_time: float = time.monotonic()
        self.last_fire_decision: bool = False

    def should_fire(self, demand_w: float) -> bool:
        """Determine if burner should be ON based on demand and state machine.

        Args:
            demand_w: Heating demand in watts. If > 0, burner is needed.

        Returns:
            True if burner should fire, False otherwise.
        """
        now = time.monotonic()
        time_in_state = now - self.state_enter_time

        old_state = self.state
        decision = False

        if self.state == BoilerState.IDLE:
            # In IDLE: can transition to HEATING if demand > 0
            if demand_w > 0:
                self.state = BoilerState.HEATING
                self.state_enter_time = now
                decision = True
                logger.info("BoilerManager: IDLE → HEATING (demand=%.0fW)", demand_w)
            else:
                decision = False

        elif self.state == BoilerState.HEATING:
            # In HEATING: stay on until min_on_time_s elapsed, then go to COOLDOWN
            if time_in_state < self.min_on_time_s:
                # Must stay on for minimum on time
                decision = True
            elif demand_w <= 0:
                # Demand satisfied, start cooldown
                self.state = BoilerState.COOLDOWN
                self.state_enter_time = now
                decision = False
                logger.info("BoilerManager: HEATING → COOLDOWN (demand satisfied)")
            else:
                # Still have demand and min on-time met; can keep heating
                decision = True

        elif self.state == BoilerState.COOLDOWN:
            # In COOLDOWN: must wait min_off_time_s before returning to IDLE
            if time_in_state < self.min_off_time_s:
                decision = False
            else:
                # Cooldown period complete; back to IDLE
                self.state = BoilerState.IDLE
                self.state_enter_time = now
                decision = False
                logger.info("BoilerManager: COOLDOWN → IDLE")

        # State transition logging
        if old_state != self.state:
            logger.info(
                "BoilerManager transition: %s → %s (time_in_state=%.1fs)",
                old_state.value,
                self.state.value,
                time_in_state,
            )

        self.last_fire_decision = decision
        return decision

    def get_state(self) -> BoilerState:
        """Return current state."""
        return self.state

    def get_state_duration(self) -> float:
        """Return seconds in current state."""
        now = time.monotonic()
        return now - self.state_enter_time

    def reset(self) -> None:
        """Reset to IDLE state."""
        self.state = BoilerState.IDLE
        self.state_enter_time = time.monotonic()
        self.last_fire_decision = False
        logger.info("BoilerManager reset to IDLE")
