"""Burner anti-short-cycle manager (#1042).

Prevents boiler burner from cycling too fast (minimum on/off times).
Typical minimum cycle time: 10 minutes.

This is a lightweight datetime-based complement to boiler_manager.py,
which uses monotonic time + state machine. Use this when you need
wall-clock timestamps for logging or external event recording.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AntiShortCycleManager:
    def __init__(self, min_on_minutes: int = 10, min_off_minutes: int = 5):
        self.min_on = timedelta(minutes=min_on_minutes)
        self.min_off = timedelta(minutes=min_off_minutes)
        self._last_on: Optional[datetime] = None
        self._last_off: Optional[datetime] = None
        self._burner_on: bool = False

    def can_turn_on(self) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        now = datetime.now(timezone.utc)
        if self._burner_on:
            return False, "already_on"
        if self._last_off and (now - self._last_off) < self.min_off:
            wait = (self.min_off - (now - self._last_off)).seconds
            return False, f"min_off_not_met:{wait}s"
        return True, "ok"

    def can_turn_off(self) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        now = datetime.now(timezone.utc)
        if not self._burner_on:
            return False, "already_off"
        if self._last_on and (now - self._last_on) < self.min_on:
            wait = (self.min_on - (now - self._last_on)).seconds
            return False, f"min_on_not_met:{wait}s"
        return True, "ok"

    def record_on(self):
        self._burner_on = True
        self._last_on = datetime.now(timezone.utc)
        logger.info("Burner ON recorded")

    def record_off(self):
        self._burner_on = False
        self._last_off = datetime.now(timezone.utc)
        logger.info("Burner OFF recorded")

    @property
    def is_on(self) -> bool:
        return self._burner_on

    def get_status(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "burner_on": self._burner_on,
            "last_on": self._last_on.isoformat() if self._last_on else None,
            "last_off": self._last_off.isoformat() if self._last_off else None,
            "can_turn_on": self.can_turn_on()[0],
            "can_turn_off": self.can_turn_off()[0],
        }
