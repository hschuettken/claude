"""Schedule Manager with comfort and mode overlays (#1041).

Manages heating schedule: time-based setpoints with comfort overlays
and mode overrides (eco, comfort, away, boost).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("hems.schedule_manager")


class HeatingMode(str, Enum):
    ECO = "eco"
    COMFORT = "comfort"
    AWAY = "away"
    BOOST = "boost"
    AUTO = "auto"


@dataclass
class ScheduleSlot:
    start: time
    end: time
    setpoint: float  # °C
    days: list  # 0=Mon, 6=Sun


@dataclass
class ComfortOverlay:
    setpoint: float
    until: datetime
    reason: str


class ScheduleManager:
    """Manages heating setpoint schedule with overlays.

    Priority: boost > comfort_overlay > mode_override > schedule
    """

    DEFAULT_SCHEDULE = [
        ScheduleSlot(time(6, 0), time(8, 0), 21.0, list(range(5))),  # Weekday morning
        ScheduleSlot(time(17, 0), time(22, 0), 21.0, list(range(5))),  # Weekday evening
        ScheduleSlot(time(8, 0), time(22, 0), 21.0, [5, 6]),  # Weekend all day
    ]
    ECO_SETBACK = 18.0  # °C in eco/away mode
    BOOST_DELTA = 2.0  # °C boost above schedule

    def __init__(self) -> None:
        self.schedule: list[ScheduleSlot] = list(self.DEFAULT_SCHEDULE)
        self.mode: HeatingMode = HeatingMode.AUTO
        self.comfort_overlay: Optional[ComfortOverlay] = None

    def get_setpoint(self, now: Optional[datetime] = None) -> float:
        """Return current target setpoint considering all overlays."""
        if now is None:
            now = datetime.now()

        # Boost mode: schedule + delta
        if self.mode == HeatingMode.BOOST:
            return self._schedule_setpoint(now) + self.BOOST_DELTA

        # Away/eco: fixed setback regardless of schedule
        if self.mode in (HeatingMode.AWAY, HeatingMode.ECO):
            return self.ECO_SETBACK

        # Comfort overlay: temporary manual raise
        if self.comfort_overlay is not None:
            if now < self.comfort_overlay.until:
                return self.comfort_overlay.setpoint
            else:
                # Expired — clear it
                logger.debug(
                    "comfort overlay expired (reason=%s)", self.comfort_overlay.reason
                )
                self.comfort_overlay = None

        # Fixed comfort mode: at least 21°C
        if self.mode == HeatingMode.COMFORT:
            return max(self._schedule_setpoint(now), 21.0)

        # Auto: follow schedule exactly
        return self._schedule_setpoint(now)

    def _schedule_setpoint(self, now: datetime) -> float:
        """Get setpoint from schedule for given datetime."""
        current_time = now.time()
        weekday = now.weekday()

        for slot in self.schedule:
            if weekday in slot.days:
                if slot.start <= current_time <= slot.end:
                    return slot.setpoint

        return self.ECO_SETBACK  # Outside schedule = eco

    def set_mode(self, mode: HeatingMode) -> None:
        """Switch operating mode."""
        logger.info("schedule_manager: mode changed %s -> %s", self.mode, mode)
        self.mode = mode

    def set_comfort_overlay(
        self,
        setpoint: float,
        duration_minutes: int,
        reason: str = "manual",
    ) -> None:
        """Apply a temporary comfort override for *duration_minutes*."""
        self.comfort_overlay = ComfortOverlay(
            setpoint=setpoint,
            until=datetime.now() + timedelta(minutes=duration_minutes),
            reason=reason,
        )
        logger.info(
            "schedule_manager: comfort overlay set sp=%.1f for %dm (%s)",
            setpoint,
            duration_minutes,
            reason,
        )

    def clear_comfort_overlay(self) -> None:
        """Explicitly cancel any active comfort overlay."""
        if self.comfort_overlay is not None:
            logger.info(
                "schedule_manager: comfort overlay cleared (was: %s)",
                self.comfort_overlay.reason,
            )
        self.comfort_overlay = None

    def add_schedule_slot(self, slot: ScheduleSlot) -> None:
        """Append a custom schedule slot."""
        self.schedule.append(slot)

    def replace_schedule(self, slots: list[ScheduleSlot]) -> None:
        """Replace the entire schedule with a new set of slots."""
        self.schedule = list(slots)
        logger.info("schedule_manager: schedule replaced (%d slots)", len(slots))

    def get_status(self) -> dict:
        """Return a snapshot of current state."""
        return {
            "mode": self.mode.value,
            "current_setpoint": self.get_setpoint(),
            "comfort_overlay": (
                {
                    "setpoint": self.comfort_overlay.setpoint,
                    "until": self.comfort_overlay.until.isoformat(),
                    "reason": self.comfort_overlay.reason,
                }
                if self.comfort_overlay is not None
                else None
            ),
        }
