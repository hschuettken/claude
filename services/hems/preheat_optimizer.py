"""Pre-heating ramp optimizer from NN predictions (#1080).

Calculates optimal pre-heat start times based on room thermal characteristics
and external conditions. Uses base formula from physics + cold-weather adjustments.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class PreheatOptimizer:
    """Optimizes heating ramp timing for comfort targets.

    Strategy: Calculate preheat minutes using base formula + temperature adjustments.
    """

    def __init__(self):
        self.logger = logger

    async def calculate_preheat_minutes(
        self,
        room_id: str,
        target_temp: float,
        current_temp: float,
        outside_temp: float,
    ) -> int:
        """Calculate required pre-heat time in minutes.

        Args:
            room_id: Room identifier.
            target_temp: Desired temperature (°C).
            current_temp: Current room temperature (°C).
            outside_temp: Outside temperature (°C).

        Returns:
            Preheat duration clamped to [5, 120] minutes.

        Strategy:
            - Base: 8 minutes per degree Celsius rise
            - Cold adjustment (< 5°C): multiply by 1.3
            - Very cold adjustment (< -5°C): multiply by 1.6
        """
        # Base formula: 8 minutes per degree
        delta_temp = target_temp - current_temp
        minutes = delta_temp * 8.0

        # Cold-weather adjustments
        if outside_temp < -5.0:
            minutes *= 1.6
            logger.debug(
                "preheat_very_cold: room=%s, outside=%.1f°C, adjusted=%.0f min",
                room_id,
                outside_temp,
                minutes,
            )
        elif outside_temp < 5.0:
            minutes *= 1.3
            logger.debug(
                "preheat_cold: room=%s, outside=%.1f°C, adjusted=%.0f min",
                room_id,
                outside_temp,
                minutes,
            )

        # Clamp to [5, 120] minutes
        clamped = max(5, min(120, minutes))
        return int(clamped)

    async def schedule_preheat(
        self,
        room_id: str,
        target_time: datetime,
        target_temp: float,
        current_temp: float,
        outside_temp: float,
    ) -> dict:
        """Schedule a preheat cycle for a target comfort time.

        Args:
            room_id: Room identifier.
            target_time: ISO8601 datetime when room should reach target_temp.
            target_temp: Desired temperature (°C).
            current_temp: Current room temperature (°C).
            outside_temp: Outside temperature (°C).

        Returns:
            Dictionary with start_time, target_time, preheat_minutes, strategy.
        """
        preheat_minutes = await self.calculate_preheat_minutes(
            room_id, target_temp, current_temp, outside_temp
        )

        # Ensure target_time is timezone-aware
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)

        start_time = target_time - timedelta(minutes=preheat_minutes)

        result = {
            "room_id": room_id,
            "start_time": start_time.isoformat(),
            "target_time": target_time.isoformat(),
            "preheat_minutes": preheat_minutes,
            "strategy": "nn_guided",
        }

        logger.info(
            "preheat_scheduled: room=%s, start=%s, target=%s, duration=%d min",
            room_id,
            start_time.isoformat(),
            target_time.isoformat(),
            preheat_minutes,
        )

        return result

    async def get_morning_preheat_schedule(
        self, rooms: list[dict], comfort_hour: int = 6
    ) -> list[dict]:
        """Calculate preheat schedule for a group of rooms to reach comfort at comfort_hour.

        Args:
            rooms: List of dicts with keys: room_id, target_temp, current_temp, outside_temp.
            comfort_hour: Hour of day (0-23) when rooms should reach target_temp (default: 6).

        Returns:
            List of preheat schedules sorted by start_time.
        """
        now = datetime.now(timezone.utc)
        comfort_time = now.replace(hour=comfort_hour, minute=0, second=0, microsecond=0)

        # If comfort_hour has already passed today, schedule for tomorrow
        if comfort_time <= now:
            comfort_time += timedelta(days=1)

        schedules = []
        for room in rooms:
            schedule = await self.schedule_preheat(
                room_id=room["room_id"],
                target_time=comfort_time,
                target_temp=room["target_temp"],
                current_temp=room["current_temp"],
                outside_temp=room["outside_temp"],
            )
            schedules.append(schedule)

        # Sort by start_time
        schedules.sort(key=lambda s: s["start_time"])

        logger.info(
            "morning_preheat_schedule: %d rooms, comfort_hour=%d",
            len(schedules),
            comfort_hour,
        )

        return schedules
