"""Circulation pump scheduler for heating system control.

Manages circulation pump state based on:
- Boiler active/idle state
- Room temperature targets vs. actual temps
- Hysteresis to prevent rapid cycling
- Minimum and maximum runtime limits

Typical use:
  pump = CirculationPumpScheduler(
      min_runtime_s=600,  # 10 minutes
      max_runtime_s=3600, # 60 minutes
      temp_hysteresis_c=0.5
  )
  
  # Called every control loop tick (~10 seconds in HEMS context)
  should_pump = pump.should_pump(
      boiler_active=True,
      room_targets={'living_room': 21.0, 'bedroom': 19.0},
      room_actuals={'living_room': 20.2, 'bedroom': 18.5}
  )
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("hems.circulation_pump")


class PumpState(str, Enum):
    """Circulation pump states."""

    OFF = "off"
    ON = "on"
    COOLDOWN = "cooldown"  # Running down after reaching targets


class CirculationPumpScheduler:
    """Circulation pump state machine with runtime limits and hysteresis.

    Prevents rapid on/off cycling and ensures pump doesn't run indefinitely.

    Attributes:
        min_runtime_s: Minimum pump runtime before allowing OFF (default 600 = 10 min)
        max_runtime_s: Maximum pump runtime before forcing OFF (safety, default 3600 = 60 min)
        temp_hysteresis_c: Temperature hysteresis to prevent chatter (default 0.5°C)
    """

    def __init__(
        self,
        min_runtime_s: float = 600.0,
        max_runtime_s: float = 3600.0,
        temp_hysteresis_c: float = 0.5,
    ):
        self.min_runtime_s = min_runtime_s
        self.max_runtime_s = max_runtime_s
        self.temp_hysteresis_c = temp_hysteresis_c

        self.state = PumpState.OFF
        self.state_enter_time: float = time.monotonic()
        self.last_decision: bool = False
        self.runtime_hours: float = 0.0  # Cumulative runtime for maintenance tracking

    def should_pump(
        self,
        boiler_active: bool,
        room_targets: dict[str, float],
        room_actuals: dict[str, float],
    ) -> bool:
        """Determine if circulation pump should be ON.

        Args:
            boiler_active: Whether boiler burner is currently firing
            room_targets: Dict of room_id → target temperature (°C)
            room_actuals: Dict of room_id → current room temperature (°C)

        Returns:
            True if pump should be ON, False if OFF.

        Logic:
        - Turn ON if: boiler is active OR any room target > actual room temp
        - Turn OFF if: boiler is idle AND all rooms at or above targets (with hysteresis)
        - Enforce minimum runtime (avoid rapid cycling)
        - Enforce maximum runtime (safety limit)
        """
        now = time.monotonic()
        time_in_state = now - self.state_enter_time

        old_state = self.state
        decision = False

        # Check if any room needs heating (target > actual + hysteresis)
        any_room_needs_heating = self._check_heating_demand(room_targets, room_actuals)

        if self.state == PumpState.OFF:
            # OFF state: can transition to ON if boiler active OR heating needed
            if boiler_active or any_room_needs_heating:
                self.state = PumpState.ON
                self.state_enter_time = now
                decision = True
                logger.info(
                    "CirculationPump: OFF → ON (boiler=%s, heating_needed=%s)",
                    boiler_active,
                    any_room_needs_heating,
                )
            else:
                decision = False

        elif self.state == PumpState.ON:
            # ON state: must stay on for min_runtime_s, enforce max_runtime_s
            if time_in_state >= self.max_runtime_s:
                # Safety limit: force OFF regardless of demand
                self.state = PumpState.OFF
                self.state_enter_time = now
                self.runtime_hours += self.max_runtime_s / 3600.0
                decision = False
                logger.warning(
                    "CirculationPump: ON → OFF (max_runtime=%.0fs reached, safety limit)",
                    self.max_runtime_s,
                )
            elif time_in_state < self.min_runtime_s:
                # Must stay on for minimum on time
                decision = True
            elif boiler_active or any_room_needs_heating:
                # Boiler still running or rooms still need heat; stay on
                decision = True
            else:
                # Min runtime met, boiler off, all rooms satisfied → start cooldown
                self.state = PumpState.COOLDOWN
                self.state_enter_time = now
                decision = False
                logger.info("CirculationPump: ON → COOLDOWN (all targets met)")

        elif self.state == PumpState.COOLDOWN:
            # COOLDOWN state: pump still running but in decay phase, quickly transition to OFF
            # (Could add a small delay here for residual flow, currently direct transition)
            self.state = PumpState.OFF
            self.state_enter_time = now
            self.runtime_hours += time_in_state / 3600.0
            decision = False
            logger.info("CirculationPump: COOLDOWN → OFF (runtime=%.1fh total)", self.runtime_hours)

        # State transition logging
        if old_state != self.state:
            logger.info(
                "CirculationPump transition: %s → %s (time_in_state=%.1fs)",
                old_state.value,
                self.state.value,
                time_in_state,
            )

        self.last_decision = decision
        return decision

    def _check_heating_demand(
        self, room_targets: dict[str, float], room_actuals: dict[str, float]
    ) -> bool:
        """Check if any room needs heating.

        Returns True if any target temp > actual temp + hysteresis.
        """
        for room_id, target in room_targets.items():
            actual = room_actuals.get(room_id, 15.0)  # Default to 15°C if unknown
            # Account for hysteresis on the downside
            if target > actual + self.temp_hysteresis_c:
                logger.debug(
                    "Room %s needs heating: target=%.1f°C, actual=%.1f°C",
                    room_id,
                    target,
                    actual,
                )
                return True
        return False

    def get_state(self) -> PumpState:
        """Return current pump state."""
        return self.state

    def get_state_duration(self) -> float:
        """Return seconds in current state."""
        now = time.monotonic()
        return now - self.state_enter_time

    def get_runtime_hours(self) -> float:
        """Return cumulative runtime hours (for maintenance tracking)."""
        hours = self.runtime_hours
        if self.state == PumpState.ON:
            # Add current running session
            hours += self.get_state_duration() / 3600.0
        return hours

    def reset(self) -> None:
        """Reset pump to OFF state and zero runtime hours."""
        self.state = PumpState.OFF
        self.state_enter_time = time.monotonic()
        self.last_decision = False
        self.runtime_hours = 0.0
        logger.info("CirculationPump reset to OFF")
