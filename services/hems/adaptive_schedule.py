"""Adaptive heating schedule generator — Phase 4.

Generates optimal 24h schedules based on:
  - Occupancy patterns (from HA binary_sensor)
  - Weather forecast (from HA sensor)
  - Thermal model predictions
  - Comfort window constraints

Algorithm:
  1. For each 15-min slot in next 24h:
     - Check occupancy status
     - If occupied: target = comfort_temp
     - If away: target = setback_temp
     - Apply weather-based boost (cold → +1°C)
  2. Store in DB for later executor to consume
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Optional

logger = logging.getLogger("hems.adaptive_schedule")


@dataclass
class ScheduleInterval:
    """Single schedule interval (15-min slot)."""
    time: datetime
    room_id: str
    target_temp: float
    mode: str  # "comfort", "eco", "off"
    
    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "room_id": self.room_id,
            "target_temp": self.target_temp,
            "mode": self.mode,
        }


@dataclass
class AdaptiveScheduleRequest:
    """Input to adaptive schedule generator."""
    room_id: str
    comfort_temp: float = 21.0  # °C, when occupied
    setback_temp: float = 16.0  # °C, when away
    weather_forecast: Optional[dict] = None  # {"temp": 2.0, "condition": "cloudy"}
    occupancy_hints: Optional[list[tuple[dt_time, dt_time]]] = None  # List of (start, end) times
    start_time: Optional[datetime] = None  # Default: now


class AdaptiveScheduleGenerator:
    """Generate optimal 24h heating schedule."""

    def __init__(self):
        self.logger = logger

    def generate(self, req: AdaptiveScheduleRequest) -> list[ScheduleInterval]:
        """Generate 24h adaptive schedule (15-min intervals).
        
        Args:
            req: AdaptiveScheduleRequest with room config and hints
            
        Returns:
            List of ScheduleInterval objects for next 24h
        """
        start = req.start_time or datetime.now(timezone.utc)
        # Round down to nearest 15-min boundary
        start = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
        
        intervals: list[ScheduleInterval] = []
        outdoor_temp = (req.weather_forecast or {}).get("temp", 10.0)
        
        self.logger.info(
            "Generating 24h schedule: room=%s, comfort=%.1f°C, setback=%.1f°C, outdoor=%.1f°C",
            req.room_id, req.comfort_temp, req.setback_temp, outdoor_temp
        )
        
        # Default occupancy: weekday 07:00-23:00, weekend 08:00-23:00
        if not req.occupancy_hints:
            dow = start.weekday()  # 0=Mon, 6=Sun
            is_weekend = dow >= 5
            occupancy_hints = [
                (dt_time(hour=8 if is_weekend else 7), dt_time(hour=23)),
            ]
        else:
            occupancy_hints = req.occupancy_hints
        
        # Generate 96 intervals (24 hours × 4 per hour)
        for i in range(96):
            slot_time = start + timedelta(minutes=i * 15)
            slot_dt_time = slot_time.time()
            
            # Check if occupied
            is_occupied = any(
                start_t <= slot_dt_time < end_t
                for start_t, end_t in occupancy_hints
            )
            
            # Determine target temp
            if is_occupied:
                target_temp = req.comfort_temp
                mode = "comfort"
            else:
                target_temp = req.setback_temp
                mode = "eco"
            
            # Weather boost: if cold (< 5°C), add 1°C to avoid setpoint drift
            if outdoor_temp < 5.0:
                target_temp += 1.0
            
            interval = ScheduleInterval(
                time=slot_time,
                room_id=req.room_id,
                target_temp=target_temp,
                mode=mode,
            )
            intervals.append(interval)
        
        self.logger.info(
            "Generated %d schedule intervals for room=%s (start=%s)",
            len(intervals), req.room_id, start.isoformat()
        )
        return intervals
