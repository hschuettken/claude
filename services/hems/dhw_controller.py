"""DHW (Domestic Hot Water) controller with PV opportunistic charging (#1043).

Manages hot water heating. When PV surplus is available, heats water
opportunistically (even outside normal schedule) up to a higher setpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class DHWConfig:
    normal_setpoint: float = 55.0  # °C normal DHW setpoint
    pv_opportunistic_setpoint: float = 65.0  # °C when PV surplus available
    comfort_setpoint: float = 60.0  # °C for comfort schedule
    legionella_setpoint: float = 70.0  # °C weekly legionella cycle
    legionella_day: int = 6  # Sunday
    pv_surplus_threshold_w: float = 800.0  # W PV surplus to trigger opportunistic
    reheat_deadband: float = 5.0  # °C below setpoint before reheat


class DHWController:
    def __init__(self, config: Optional[DHWConfig] = None):
        self.config = config or DHWConfig()
        self._pv_surplus_w: float = 0.0
        self._current_temp: float = 50.0

    def update_pv_surplus(self, surplus_w: float):
        self._pv_surplus_w = surplus_w

    def update_temp(self, temp: float):
        self._current_temp = temp

    def get_target_setpoint(self, now: Optional[datetime] = None) -> float:
        if now is None:
            now = datetime.now(timezone.utc)
        # Legionella cycle (Sunday)
        if now.weekday() == self.config.legionella_day and now.hour == 2:
            return self.config.legionella_setpoint
        # PV opportunistic
        if self._pv_surplus_w >= self.config.pv_surplus_threshold_w:
            return self.config.pv_opportunistic_setpoint
        return self.config.normal_setpoint

    def needs_reheat(self, now: Optional[datetime] = None) -> bool:
        target = self.get_target_setpoint(now)
        return self._current_temp < (target - self.config.reheat_deadband)

    def get_status(self) -> dict:
        return {
            "current_temp": self._current_temp,
            "target_setpoint": self.get_target_setpoint(),
            "needs_reheat": self.needs_reheat(),
            "pv_surplus_w": self._pv_surplus_w,
            "pv_opportunistic_active": self._pv_surplus_w
            >= self.config.pv_surplus_threshold_w,
        }
