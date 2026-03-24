"""Circulation pump scheduler for heating system control.

Manages circulation pump state based on:
- Time-window scheduling (configurable morning/evening peaks)
- Boiler active/idle state
- Room temperature targets vs. actual temps
- Hysteresis to prevent rapid cycling
- Minimum and maximum runtime limits

Typical use:
  pump = CirculationPumpScheduler(
      min_runtime_s=600,  # 10 minutes
      max_runtime_s=3600, # 60 minutes
      temp_hysteresis_c=0.5,
      time_windows=[
          TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0),     # Morning
          TimeWindow(hour=17, minute=0, end_hour=21, end_minute=0),    # Evening
      ]
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
from datetime import datetime, time as time_type
from enum import Enum
from typing import Optional

logger = logging.getLogger("hems.circulation_pump")


class TimeWindow:
    """Represents a time window for circulation pump scheduling.
    
    Example:
        # Morning window: 06:30-08:00
        window = TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0)
    """
    
    def __init__(self, hour: int, minute: int, end_hour: int, end_minute: int):
        """Initialize a time window.
        
        Args:
            hour: Start hour (0-23)
            minute: Start minute (0-59)
            end_hour: End hour (0-23)
            end_minute: End minute (0-59)
        """
        self.start_time = time_type(hour, minute)
        self.end_time = time_type(end_hour, end_minute)
    
    def is_active(self, current_time: Optional[time_type] = None) -> bool:
        """Check if current time falls within this window.
        
        Args:
            current_time: Time to check (defaults to current local time)
            
        Returns:
            True if current_time is within the window, False otherwise.
        """
        if current_time is None:
            current_time = datetime.now().time()
        
        # Handle windows that wrap around midnight (e.g., 22:00-06:00)
        if self.start_time <= self.end_time:
            # Normal window (doesn't wrap midnight)
            return self.start_time <= current_time < self.end_time
        else:
            # Window wraps midnight
            return current_time >= self.start_time or current_time < self.end_time
    
    def __repr__(self) -> str:
        return f"TimeWindow({self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')})"


class PumpState(str, Enum):
    """Circulation pump states."""

    OFF = "off"
    ON = "on"
    COOLDOWN = "cooldown"  # Running down after reaching targets


class CirculationPumpScheduler:
    """Circulation pump state machine with runtime limits, hysteresis, and time-window scheduling.

    Prevents rapid on/off cycling and ensures pump doesn't run indefinitely.
    Supports configurable time windows for scheduled circulation pump activation.

    Attributes:
        min_runtime_s: Minimum pump runtime before allowing OFF (default 600 = 10 min)
        max_runtime_s: Maximum pump runtime before forcing OFF (safety, default 3600 = 60 min)
        temp_hysteresis_c: Temperature hysteresis to prevent chatter (default 0.5°C)
        time_windows: List of TimeWindow objects defining scheduled pump times
    """

    def __init__(
        self,
        min_runtime_s: float = 600.0,
        max_runtime_s: float = 3600.0,
        temp_hysteresis_c: float = 0.5,
        time_windows: Optional[list[TimeWindow]] = None,
    ):
        self.min_runtime_s = min_runtime_s
        self.max_runtime_s = max_runtime_s
        self.temp_hysteresis_c = temp_hysteresis_c
        
        # Default time windows: 06:30-08:00 (morning), 17:00-21:00 (evening)
        if time_windows is None:
            self.time_windows = [
                TimeWindow(hour=6, minute=30, end_hour=8, end_minute=0),    # Morning peak
                TimeWindow(hour=17, minute=0, end_hour=21, end_minute=0),   # Evening peak
            ]
        else:
            self.time_windows = time_windows

        self.state = PumpState.OFF
        self.state_enter_time: float = time.monotonic()
        self.last_decision: bool = False
        self.runtime_hours: float = 0.0  # Cumulative runtime for maintenance tracking
        self.in_scheduled_window: bool = False  # Track if we're in a scheduled time window

    def _is_in_scheduled_window(self, current_time: Optional[time_type] = None) -> bool:
        """Check if current time falls within any scheduled pump window.
        
        Args:
            current_time: Time to check (defaults to current local time)
            
        Returns:
            True if in any active time window, False otherwise.
        """
        if current_time is None:
            current_time = datetime.now().time()
        
        return any(window.is_active(current_time) for window in self.time_windows)

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
        - Turn ON if: scheduled window active OR boiler is active OR any room target > actual room temp
        - Turn OFF if: not in scheduled window AND boiler is idle AND all rooms at or above targets (with hysteresis)
        - Enforce minimum runtime (avoid rapid cycling)
        - Enforce maximum runtime (safety limit)
        """
        now = time.monotonic()
        time_in_state = now - self.state_enter_time

        old_state = self.state
        decision = False

        # Check scheduled time windows
        self.in_scheduled_window = self._is_in_scheduled_window()
        
        # Check if any room needs heating (target > actual + hysteresis)
        any_room_needs_heating = self._check_heating_demand(room_targets, room_actuals)

        if self.state == PumpState.OFF:
            # OFF state: can transition to ON if boiler active OR heating needed OR in scheduled window
            should_turn_on = (
                boiler_active 
                or any_room_needs_heating 
                or self.in_scheduled_window
            )
            if should_turn_on:
                self.state = PumpState.ON
                self.state_enter_time = now
                decision = True
                logger.info(
                    "CirculationPump: OFF → ON (boiler=%s, heating_needed=%s, scheduled=%s)",
                    boiler_active,
                    any_room_needs_heating,
                    self.in_scheduled_window,
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
            elif boiler_active or any_room_needs_heating or self.in_scheduled_window:
                # Boiler still running or rooms still need heat or in scheduled window; stay on
                decision = True
            else:
                # Min runtime met, boiler off, all rooms satisfied, not in scheduled window → start cooldown
                self.state = PumpState.COOLDOWN
                self.state_enter_time = now
                decision = False
                logger.info("CirculationPump: ON → COOLDOWN (all targets met, not in scheduled window)")

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

    def get_time_windows(self) -> list[TimeWindow]:
        """Return current time windows configuration."""
        return self.time_windows

    def set_time_windows(self, time_windows: list[TimeWindow]) -> None:
        """Update time windows configuration.
        
        Args:
            time_windows: List of new TimeWindow objects to use for scheduling.
            
        Raises:
            ValueError: If time_windows is empty.
        """
        if not time_windows:
            raise ValueError("time_windows cannot be empty")
        self.time_windows = time_windows
        logger.info("CirculationPump time_windows updated: %s", self.time_windows)

    def reset(self) -> None:
        """Reset pump to OFF state and zero runtime hours."""
        self.state = PumpState.OFF
        self.state_enter_time = time.monotonic()
        self.last_decision = False
        self.runtime_hours = 0.0
        self.in_scheduled_window = False
        logger.info("CirculationPump reset to OFF")
