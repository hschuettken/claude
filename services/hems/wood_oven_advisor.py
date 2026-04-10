"""Wood oven advisor with optimal start time (#1047).

Calculates when to start the wood oven to reach target room temperature
by a desired time, accounting for thermal mass and outside temperature.

Usage:
    from wood_oven_advisor import WoodOvenAdvisor
    advisor = WoodOvenAdvisor()
    result = advisor.get_daily_recommendation(current_temp=18.0, outside_temp=3.0)
    print(result["advice"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WoodOvenConfig:
    """Tunable parameters for the thermal model.

    Attributes:
        warmup_minutes_per_degree: Minutes required to raise room temp by 1 °C
            under typical conditions.
        max_output_kw: Nominal output power (informational only).
        typical_burn_time_hours: Expected firing duration per session.
        cold_start_overhead_minutes: Extra lead-time when the room is cold
            (< 15 °C) due to chimney warm-up and slow initial heat release.
    """

    warmup_minutes_per_degree: float = 8.0
    max_output_kw: float = 8.0
    typical_burn_time_hours: float = 3.0
    cold_start_overhead_minutes: int = 30


class WoodOvenAdvisor:
    """Advises on optimal wood oven start time.

    Uses a simple linear thermal model:
        warmup_time = (target_temp − current_temp) × warmup_rate

    The rate is adjusted for outside temperature (colder outside → more heat
    loss → longer warmup) and for a cold-start overhead when the room is very
    cold.
    """

    def __init__(self, config: Optional[WoodOvenConfig] = None) -> None:
        self.config = config or WoodOvenConfig()

    def calculate_start_time(
        self,
        target_temp: float,
        current_temp: float,
        desired_ready_by: datetime,
        outside_temp: float = 5.0,
    ) -> dict:
        """Calculate when to start the wood oven.

        Args:
            target_temp: Desired room temperature in °C.
            current_temp: Current room temperature in °C.
            desired_ready_by: Timezone-aware datetime by which the room should
                reach target_temp.  Pass a UTC-aware datetime for consistency.
            outside_temp: Current outside temperature in °C (affects heat loss).

        Returns:
            Dict with keys:
                start_time (ISO-8601 str), warmup_minutes (int),
                minutes_until_start (int), advice (str), urgency (str),
                delta_temp (float), outside_temp (float).
        """
        delta = max(0.0, target_temp - current_temp)

        # Base warmup time (linear)
        warmup_minutes = delta * self.config.warmup_minutes_per_degree

        # Outside temperature correction — colder outside = higher heat loss
        if outside_temp < 0.0:
            warmup_minutes *= 1.3
        elif outside_temp < 5.0:
            warmup_minutes *= 1.15

        # Cold-start overhead: chimney takes time to draft when room is cold
        if current_temp < 15.0:
            warmup_minutes += self.config.cold_start_overhead_minutes

        # Enforce a minimum sensible warmup floor
        warmup_minutes = max(30.0, warmup_minutes)

        start_time = desired_ready_by - timedelta(minutes=warmup_minutes)
        now = datetime.now(timezone.utc)

        minutes_until_start = (start_time - now).total_seconds() / 60.0

        if minutes_until_start < 0:
            advice = "Start now — already behind schedule"
            urgency = "urgent"
        elif minutes_until_start < 15:
            advice = f"Start in {int(minutes_until_start)} minutes"
            urgency = "soon"
        else:
            # Format in local-ish wall time for display (simplified: UTC+1)
            local_start = start_time + timedelta(hours=1)
            advice = f"Start at {local_start.strftime('%H:%M')} (in {int(minutes_until_start)} min)"
            urgency = "ok"

        return {
            "start_time": start_time.isoformat(),
            "warmup_minutes": round(warmup_minutes),
            "minutes_until_start": round(minutes_until_start),
            "advice": advice,
            "urgency": urgency,
            "delta_temp": round(delta, 1),
            "outside_temp": outside_temp,
        }

    def get_daily_recommendation(
        self,
        current_temp: float,
        outside_temp: float,
        target_evening_temp: float = 21.0,
        evening_hour: int = 18,
    ) -> dict:
        """Get recommendation for this evening's heating.

        Args:
            current_temp: Current room temperature in °C.
            outside_temp: Current outside temperature in °C.
            target_evening_temp: Desired room temperature for the evening.
            evening_hour: Target local hour (24h, CET/CEST approximated as
                UTC+1).  If already past this hour, target is set for the
                following day.

        Returns:
            Same dict as calculate_start_time().
        """
        now_utc = datetime.now(timezone.utc)
        # Approximate CET/CEST as UTC+1 — good enough for a start-time advisor
        local_hour = (now_utc.hour + 1) % 24

        # Target: the hour before the desired ready time (fire should be going
        # strong by evening_hour, so we target evening_hour−1 as start-ready)
        if local_hour >= evening_hour:
            # It's already past evening time — target tomorrow
            target_utc = (now_utc + timedelta(days=1)).replace(
                hour=(evening_hour - 1) % 24, minute=0, second=0, microsecond=0
            )
        else:
            target_utc = now_utc.replace(
                hour=(evening_hour - 1) % 24, minute=0, second=0, microsecond=0
            )
            if target_utc <= now_utc:
                # Edge case: same hour, already past
                target_utc += timedelta(days=1)

        return self.calculate_start_time(
            target_temp=target_evening_temp,
            current_temp=current_temp,
            desired_ready_by=target_utc,
            outside_temp=outside_temp,
        )
