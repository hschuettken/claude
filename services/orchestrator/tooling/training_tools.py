"""Training and performance trend analysis tools for Orbit.

Integrates with intervals.icu to provide:
- CTL (Chronic Training Load) — 42-day exponential moving average
- ATL (Acute Training Load) — 7-day exponential moving average
- TSS (Training Stress Score) — per-activity performance metric
- Performance trend estimation and overtraining detection
- Fitness improvement prediction
"""

from __future__ import annotations

import os
from typing import Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import math

import httpx

from shared.log import get_logger

logger = get_logger("tooling.training_tools")

# intervals.icu API base URL
INTERVALS_ICU_BASE = "https://intervals.icu/api/v1"

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_performance_trend",
            "description": (
                "Get performance trend analysis from intervals.icu data. "
                "Returns CTL (fitness), ATL (fatigue), TSB (training stress balance), "
                "fitness direction, and overtraining risk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "athlete_id": {
                        "type": "string",
                        "description": "intervals.icu athlete ID",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "intervals.icu API key (will use NB9OS stored key if not provided)",
                    },
                    "days_lookback": {
                        "type": "integer",
                        "description": "Days of history to analyze (default: 90)",
                    },
                },
                "required": ["athlete_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_fitness_improvement",
            "description": (
                "Predict expected pace/performance improvement based on recent training load, "
                "recovery metrics, and VO2max trend from intervals.icu data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "athlete_id": {
                        "type": "string",
                        "description": "intervals.icu athlete ID",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "intervals.icu API key (will use NB9OS stored key if not provided)",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "Days ahead to predict (default: 14)",
                    },
                },
                "required": ["athlete_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_overtraining_risk",
            "description": (
                "Detect overtraining risk based on CTL, ATL, HRV, sleep, and stress metrics "
                "from intervals.icu wellness data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "athlete_id": {
                        "type": "string",
                        "description": "intervals.icu athlete ID",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "intervals.icu API key (will use NB9OS stored key if not provided)",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Risk threshold (default: 0.7, range 0-1)",
                    },
                },
                "required": ["athlete_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekly_training_load",
            "description": (
                "Get weekly training load summary: total TSS, number of workouts, "
                "distribution by intensity zone, and weekly volume trend."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "athlete_id": {
                        "type": "string",
                        "description": "intervals.icu athlete ID",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "intervals.icu API key (will use NB9OS stored key if not provided)",
                    },
                    "weeks": {
                        "type": "integer",
                        "description": "Number of weeks to analyze (default: 4)",
                    },
                },
                "required": ["athlete_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recovery_status",
            "description": (
                "Get current recovery status based on HRV, sleep quality, body battery, "
                "resting HR, and stress metrics from intervals.icu wellness data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "athlete_id": {
                        "type": "string",
                        "description": "intervals.icu athlete ID",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "intervals.icu API key (will use NB9OS stored key if not provided)",
                    },
                    "days_lookback": {
                        "type": "integer",
                        "description": "Days of wellness data to analyze (default: 14)",
                    },
                },
                "required": ["athlete_id"],
            },
        },
    },
]


@dataclass
class WellnessData:
    """Wellness record from intervals.icu."""

    date: str
    hrv_rmssd: Optional[float] = None
    resting_hr: Optional[float] = None
    body_battery_start: Optional[float] = None
    body_battery_end: Optional[float] = None
    sleep_hours: Optional[float] = None
    sleep_score: Optional[float] = None
    stress_avg: Optional[float] = None
    spo2_avg: Optional[float] = None


@dataclass
class ActivityData:
    """Activity record from intervals.icu."""

    activity_id: str
    date: str
    sport_type: str
    duration_seconds: int
    distance_m: float
    elevation_m: float
    avg_hr: float
    max_hr: float
    normalized_power: Optional[float] = None
    tss: Optional[float] = None
    avg_pace_ms: Optional[float] = None


class TrainingTrendAnalyzer:
    """Analyze training trends using intervals.icu data.
    
    Implements:
    - CTL (Chronic Training Load): 42-day EMA of TSS
    - ATL (Acute Training Load): 7-day EMA of TSS
    - TSB (Training Stress Balance): CTL - ATL
    - Overtraining risk detection
    - Performance improvement prediction
    """

    def __init__(self, api_key: str, athlete_id: str):
        self.api_key = api_key
        self.athlete_id = athlete_id
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        """Build Basic Auth header for intervals.icu."""
        import base64

        credentials = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

    async def fetch_activities(
        self, days_lookback: int = 90
    ) -> list[ActivityData]:
        """Fetch activities from intervals.icu."""
        client = await self._get_client()
        oldest = (datetime.now() - timedelta(days=days_lookback)).date().isoformat()
        newest = datetime.now().date().isoformat()

        try:
            resp = await client.get(
                f"{INTERVALS_ICU_BASE}/athlete/{self.athlete_id}/activities",
                params={"oldest": oldest, "newest": newest},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            activities = []
            for activity in data:
                activities.append(
                    ActivityData(
                        activity_id=activity.get("id", ""),
                        date=activity.get("start", "")[:10],
                        sport_type=activity.get("sport", ""),
                        duration_seconds=int(activity.get("duration", 0) or 0),
                        distance_m=float(activity.get("distance", 0) or 0),
                        elevation_m=float(activity.get("elevation_gain", 0) or 0),
                        avg_hr=float(activity.get("avg_hr", 0) or 0),
                        max_hr=float(activity.get("max_hr", 0) or 0),
                        normalized_power=float(activity.get("np", 0) or 0),
                        tss=float(activity.get("tss", 0) or 0),
                        avg_pace_ms=float(activity.get("avg_pace", 0) or 0),
                    )
                )
            
            logger.info(
                "Fetched %d activities for athlete %s", len(activities), self.athlete_id
            )
            return activities

        except httpx.HTTPError as e:
            logger.error("Failed to fetch activities: %s", e)
            raise

    async def fetch_wellness(
        self, days_lookback: int = 90
    ) -> list[WellnessData]:
        """Fetch wellness data from intervals.icu."""
        client = await self._get_client()
        oldest = (datetime.now() - timedelta(days=days_lookback)).date().isoformat()
        newest = datetime.now().date().isoformat()

        try:
            resp = await client.get(
                f"{INTERVALS_ICU_BASE}/athlete/{self.athlete_id}/wellness",
                params={"oldest": oldest, "newest": newest},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            wellness = []
            for record in data:
                wellness.append(
                    WellnessData(
                        date=record.get("date", "")[:10],
                        hrv_rmssd=record.get("hrv"),
                        resting_hr=record.get("rhr"),
                        body_battery_start=record.get("bb_start"),
                        body_battery_end=record.get("bb_end"),
                        sleep_hours=record.get("sleep_time") and record.get("sleep_time") / 3600,
                        sleep_score=record.get("sleep_score"),
                        stress_avg=record.get("stress"),
                        spo2_avg=record.get("spo2"),
                    )
                )
            
            logger.info(
                "Fetched %d wellness records for athlete %s",
                len(wellness),
                self.athlete_id,
            )
            return wellness

        except httpx.HTTPError as e:
            logger.error("Failed to fetch wellness data: %s", e)
            raise

    def calculate_ctl_atl_tsb(
        self, activities: list[ActivityData]
    ) -> dict[str, Any]:
        """Calculate CTL, ATL, and TSB from activities.
        
        CTL (Chronic Training Load): 42-day exponential moving average
        ATL (Acute Training Load): 7-day exponential moving average
        TSB (Training Stress Balance): CTL - ATL
        
        Returns daily values for the last activity date.
        """
        if not activities:
            return {
                "ctl": 0,
                "atl": 0,
                "tsb": 0,
                "trend": "no_data",
                "daily_values": [],
            }

        # Group activities by date, summing TSS per day
        daily_tss: dict[str, float] = {}
        for activity in activities:
            date = activity.date
            tss = activity.tss or 0
            daily_tss[date] = daily_tss.get(date, 0) + tss

        # Sort dates
        sorted_dates = sorted(daily_tss.keys())

        # Calculate CTL and ATL for each day
        ctl_values = []
        atl_values = []
        daily_values = []

        ctl = 0.0
        atl = 0.0
        ctl_decay = math.exp(-1.0 / 42.0)  # 42-day decay
        atl_decay = math.exp(-1.0 / 7.0)  # 7-day decay

        for date in sorted_dates:
            tss = daily_tss[date]

            # Update CTL and ATL
            ctl = ctl * ctl_decay + tss * (1 - ctl_decay)
            atl = atl * atl_decay + tss * (1 - atl_decay)
            tsb = ctl - atl

            ctl_values.append(ctl)
            atl_values.append(atl)

            daily_values.append(
                {
                    "date": date,
                    "tss": tss,
                    "ctl": round(ctl, 1),
                    "atl": round(atl, 1),
                    "tsb": round(tsb, 1),
                }
            )

        # Determine trend direction (last 14 days vs previous 14 days)
        if len(ctl_values) >= 28:
            ctl_recent = sum(ctl_values[-14:]) / 14
            ctl_previous = sum(ctl_values[-28:-14]) / 14
            trend_delta = ctl_recent - ctl_previous
            if trend_delta > 5:
                trend = "improving"
            elif trend_delta < -5:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        latest = daily_values[-1] if daily_values else {}

        return {
            "ctl": latest.get("ctl", 0),
            "atl": latest.get("atl", 0),
            "tsb": latest.get("tsb", 0),
            "trend": trend,
            "last_date": latest.get("date"),
            "daily_values": daily_values[-30:],  # Return last 30 days
        }

    def detect_overtraining(
        self, ctl: float, atl: float, wellness: list[WellnessData]
    ) -> dict[str, Any]:
        """Detect overtraining risk based on CTL/ATL and wellness metrics."""
        risk_score = 0.0
        risk_factors = []

        # Factor 1: Acute load too high relative to chronic load (ATL > CTL)
        if ctl > 0 and atl > ctl:
            load_ratio = atl / ctl
            if load_ratio > 1.3:
                risk_score += 0.3
                risk_factors.append(
                    f"High acute load relative to fitness (ATL/CTL = {load_ratio:.1f})"
                )

        # Factor 2: Declining sleep quality
        if len(wellness) >= 7:
            recent_sleep = [
                w.sleep_score for w in wellness[-7:] if w.sleep_score
            ]
            if len(recent_sleep) >= 3:
                avg_recent = sum(recent_sleep) / len(recent_sleep)
                if avg_recent < 75:
                    risk_score += 0.2
                    risk_factors.append(f"Poor sleep quality (avg: {avg_recent:.0f})")

        # Factor 3: High resting HR
        if len(wellness) >= 7:
            recent_rhr = [w.resting_hr for w in wellness[-7:] if w.resting_hr]
            if len(recent_rhr) >= 3:
                avg_rhr = sum(recent_rhr) / len(recent_rhr)
                # Assume baseline ~60; if elevated >10% = risk
                if avg_rhr > 66:
                    risk_score += 0.2
                    risk_factors.append(f"Elevated resting HR ({avg_rhr:.0f})")

        # Factor 4: Low HRV
        if len(wellness) >= 7:
            recent_hrv = [w.hrv_rmssd for w in wellness[-7:] if w.hrv_rmssd]
            if len(recent_hrv) >= 3:
                avg_hrv = sum(recent_hrv) / len(recent_hrv)
                if avg_hrv < 30:  # Typically healthy is 40+
                    risk_score += 0.2
                    risk_factors.append(f"Low HRV ({avg_hrv:.0f} ms)")

        # Factor 5: Low body battery
        if len(wellness) >= 3:
            recent_bb = [
                w.body_battery_end for w in wellness[-3:] if w.body_battery_end
            ]
            if len(recent_bb) >= 2:
                avg_bb = sum(recent_bb) / len(recent_bb)
                if avg_bb < 30:
                    risk_score += 0.1
                    risk_factors.append(f"Low body battery ({avg_bb:.0f})")

        return {
            "risk_score": min(risk_score, 1.0),
            "is_overtraining": risk_score >= 0.7,
            "risk_factors": risk_factors,
            "recommendation": _overtraining_recommendation(risk_score, risk_factors),
        }

    def predict_performance_improvement(
        self, activities: list[ActivityData], wellness: list[WellnessData]
    ) -> dict[str, Any]:
        """Predict pace improvement based on training response."""
        if not activities:
            return {"improvement_percent": 0, "prediction_confidence": 0}

        # Extract running activities only (with pace data)
        running_activities = [
            a for a in activities if a.avg_pace_ms and a.sport_type in ["run", "trail_run"]
        ]

        if len(running_activities) < 10:
            return {
                "improvement_percent": 0,
                "prediction_confidence": 0,
                "reason": "insufficient_running_data",
            }

        # Organize by weeks
        weekly_data = {}
        for activity in running_activities:
            week_key = datetime.fromisoformat(activity.date).isocalendar()[1]
            if week_key not in weekly_data:
                weekly_data[week_key] = {
                    "paces": [],
                    "tss": [],
                    "count": 0,
                }
            weekly_data[week_key]["paces"].append(activity.avg_pace_ms)
            if activity.tss:
                weekly_data[week_key]["tss"].append(activity.tss)
            weekly_data[week_key]["count"] += 1

        if len(weekly_data) < 4:
            return {
                "improvement_percent": 0,
                "prediction_confidence": 0,
                "reason": "insufficient_weeks_of_data",
            }

        sorted_weeks = sorted(weekly_data.keys())

        # Calculate average pace per week
        weekly_paces = []
        for week in sorted_weeks[-8:]:  # Last 8 weeks
            paces = weekly_data[week]["paces"]
            avg_pace = sum(paces) / len(paces)
            weekly_paces.append(avg_pace)

        # Calculate pace improvement trend
        if len(weekly_paces) >= 4:
            early_avg = sum(weekly_paces[:4]) / 4
            recent_avg = sum(weekly_paces[-4:]) / 4
            pace_improvement = (early_avg - recent_avg) / early_avg * 100

            # Cap prediction at ±10%
            pace_improvement = max(-10, min(10, pace_improvement))

            return {
                "improvement_percent": round(pace_improvement, 1),
                "prediction_confidence": 0.7 if len(running_activities) >= 20 else 0.5,
                "improvement_direction": "faster"
                if pace_improvement > 0
                else "slower" if pace_improvement < 0 else "stable",
                "expected_pace_improvement_secs_per_km": round(
                    pace_improvement / 100 * recent_avg, 1
                ),
            }

        return {"improvement_percent": 0, "prediction_confidence": 0}


class TrainingTools:
    """Handler for training analysis tools."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def get_performance_trend(
        self,
        athlete_id: str,
        api_key: Optional[str] = None,
        days_lookback: int = 90,
    ) -> dict[str, Any]:
        """Get complete performance trend analysis."""
        if not api_key:
            api_key = os.environ.get("INTERVALS_ICU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "intervals.icu API key not provided and INTERVALS_ICU_API_KEY not set"
            )

        analyzer = TrainingTrendAnalyzer(api_key, athlete_id)

        try:
            activities = await analyzer.fetch_activities(days_lookback)
            wellness = await analyzer.fetch_wellness(days_lookback)

            trend_data = analyzer.calculate_ctl_atl_tsb(activities)
            overtraining = analyzer.detect_overtraining(
                trend_data["ctl"], trend_data["atl"], wellness
            )

            return {
                "athlete_id": athlete_id,
                "as_of": datetime.now().isoformat(),
                "fitness_trend": {
                    "ctl": trend_data["ctl"],
                    "atl": trend_data["atl"],
                    "tsb": trend_data["tsb"],
                    "trend_direction": trend_data["trend"],
                    "last_update": trend_data.get("last_date"),
                },
                "overtraining_risk": overtraining,
                "recent_daily_values": trend_data.get("daily_values", []),
            }

        except Exception as e:
            logger.error("Failed to get performance trend: %s", e)
            raise

    async def predict_fitness_improvement(
        self,
        athlete_id: str,
        api_key: Optional[str] = None,
        days_ahead: int = 14,
    ) -> dict[str, Any]:
        """Predict fitness improvement."""
        if not api_key:
            api_key = os.environ.get("INTERVALS_ICU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "intervals.icu API key not provided and INTERVALS_ICU_API_KEY not set"
            )

        analyzer = TrainingTrendAnalyzer(api_key, athlete_id)

        try:
            activities = await analyzer.fetch_activities(90)
            wellness = await analyzer.fetch_wellness(90)

            prediction = analyzer.predict_performance_improvement(activities, wellness)

            return {
                "athlete_id": athlete_id,
                "prediction_window_days": days_ahead,
                "as_of": datetime.now().isoformat(),
                "predicted_improvement": prediction,
                "confidence": prediction.get("prediction_confidence", 0),
            }

        except Exception as e:
            logger.error("Failed to predict fitness improvement: %s", e)
            raise

    async def detect_overtraining_risk(
        self,
        athlete_id: str,
        api_key: Optional[str] = None,
        threshold: float = 0.7,
    ) -> dict[str, Any]:
        """Detect overtraining risk."""
        if not api_key:
            api_key = os.environ.get("INTERVALS_ICU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "intervals.icu API key not provided and INTERVALS_ICU_API_KEY not set"
            )

        analyzer = TrainingTrendAnalyzer(api_key, athlete_id)

        try:
            activities = await analyzer.fetch_activities(90)
            wellness = await analyzer.fetch_wellness(90)

            trend_data = analyzer.calculate_ctl_atl_tsb(activities)
            overtraining = analyzer.detect_overtraining(
                trend_data["ctl"], trend_data["atl"], wellness
            )

            return {
                "athlete_id": athlete_id,
                "as_of": datetime.now().isoformat(),
                "risk_threshold": threshold,
                "overtraining_detected": overtraining["risk_score"] >= threshold,
                "risk_assessment": overtraining,
            }

        except Exception as e:
            logger.error("Failed to detect overtraining risk: %s", e)
            raise

    async def get_weekly_training_load(
        self,
        athlete_id: str,
        api_key: Optional[str] = None,
        weeks: int = 4,
    ) -> dict[str, Any]:
        """Get weekly training load summary."""
        if not api_key:
            api_key = os.environ.get("INTERVALS_ICU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "intervals.icu API key not provided and INTERVALS_ICU_API_KEY not set"
            )

        analyzer = TrainingTrendAnalyzer(api_key, athlete_id)

        try:
            activities = await analyzer.fetch_activities(days_lookback=weeks * 7 + 14)

            # Group activities by week
            weekly_load: dict[int, dict[str, Any]] = {}
            for activity in activities:
                week_num = datetime.fromisoformat(activity.date).isocalendar()[1]
                if week_num not in weekly_load:
                    weekly_load[week_num] = {
                        "total_tss": 0,
                        "total_duration_hours": 0,
                        "workout_count": 0,
                        "by_zone": {
                            "z1_recovery": 0,
                            "z2_base": 0,
                            "z3_tempo": 0,
                            "z4_threshold": 0,
                            "z5_vo2": 0,
                        },
                        "sports": {},
                    }

                week = weekly_load[week_num]
                tss = activity.tss or 0
                week["total_tss"] += tss
                week["total_duration_hours"] += activity.duration_seconds / 3600
                week["workout_count"] += 1

                # Simple zone classification based on TSS per hour
                tss_per_hour = tss / (activity.duration_seconds / 3600) if activity.duration_seconds > 0 else 0
                if tss_per_hour < 1:
                    week["by_zone"]["z1_recovery"] += 1
                elif tss_per_hour < 1.5:
                    week["by_zone"]["z2_base"] += 1
                elif tss_per_hour < 2:
                    week["by_zone"]["z3_tempo"] += 1
                elif tss_per_hour < 3:
                    week["by_zone"]["z4_threshold"] += 1
                else:
                    week["by_zone"]["z5_vo2"] += 1

                # Track sports
                sport = activity.sport_type
                if sport not in week["sports"]:
                    week["sports"][sport] = 0
                week["sports"][sport] += 1

            sorted_weeks = sorted(weekly_load.keys())

            return {
                "athlete_id": athlete_id,
                "weeks_analyzed": weeks,
                "as_of": datetime.now().isoformat(),
                "weekly_summary": [
                    {
                        "week_number": w,
                        **weekly_load[w],
                    }
                    for w in sorted_weeks[-weeks:]
                ],
            }

        except Exception as e:
            logger.error("Failed to get weekly training load: %s", e)
            raise

    async def get_recovery_status(
        self,
        athlete_id: str,
        api_key: Optional[str] = None,
        days_lookback: int = 14,
    ) -> dict[str, Any]:
        """Get current recovery status."""
        if not api_key:
            api_key = os.environ.get("INTERVALS_ICU_API_KEY", "")
        if not api_key:
            raise ValueError(
                "intervals.icu API key not provided and INTERVALS_ICU_API_KEY not set"
            )

        analyzer = TrainingTrendAnalyzer(api_key, athlete_id)

        try:
            wellness = await analyzer.fetch_wellness(days_lookback)

            if not wellness:
                return {
                    "athlete_id": athlete_id,
                    "status": "no_data",
                    "message": "No wellness data available",
                }

            # Analyze recent trend (last 7 days if available)
            recent = wellness[-min(7, len(wellness)) :]

            metrics = {
                "hrv_rmssd": [w.hrv_rmssd for w in recent if w.hrv_rmssd],
                "resting_hr": [w.resting_hr for w in recent if w.resting_hr],
                "sleep_hours": [w.sleep_hours for w in recent if w.sleep_hours],
                "sleep_score": [w.sleep_score for w in recent if w.sleep_score],
                "body_battery_end": [w.body_battery_end for w in recent if w.body_battery_end],
                "stress_avg": [w.stress_avg for w in recent if w.stress_avg],
            }

            recovery_score = 0
            recovery_factors = []

            # HRV assessment
            if metrics["hrv_rmssd"]:
                avg_hrv = sum(metrics["hrv_rmssd"]) / len(metrics["hrv_rmssd"])
                if avg_hrv > 50:
                    recovery_score += 30
                    recovery_factors.append(f"Excellent HRV ({avg_hrv:.0f})")
                elif avg_hrv > 30:
                    recovery_score += 20
                    recovery_factors.append(f"Good HRV ({avg_hrv:.0f})")
                else:
                    recovery_factors.append(f"Low HRV ({avg_hrv:.0f})")

            # Sleep assessment
            if metrics["sleep_hours"]:
                avg_sleep = sum(metrics["sleep_hours"]) / len(metrics["sleep_hours"])
                if avg_sleep >= 7:
                    recovery_score += 25
                    recovery_factors.append(f"Adequate sleep ({avg_sleep:.1f}h)")
                elif avg_sleep >= 6:
                    recovery_score += 15
                    recovery_factors.append(f"Borderline sleep ({avg_sleep:.1f}h)")
                else:
                    recovery_factors.append(f"Insufficient sleep ({avg_sleep:.1f}h)")

            # Resting HR assessment
            if metrics["resting_hr"]:
                avg_rhr = sum(metrics["resting_hr"]) / len(metrics["resting_hr"])
                if avg_rhr <= 60:
                    recovery_score += 20
                    recovery_factors.append(f"Good RHR ({avg_rhr:.0f})")
                elif avg_rhr <= 70:
                    recovery_score += 10
                    recovery_factors.append(f"Elevated RHR ({avg_rhr:.0f})")
                else:
                    recovery_factors.append(f"High RHR ({avg_rhr:.0f})")

            # Body battery
            if metrics["body_battery_end"]:
                avg_bb = sum(metrics["body_battery_end"]) / len(metrics["body_battery_end"])
                if avg_bb >= 70:
                    recovery_score += 15
                    recovery_factors.append(f"High battery ({avg_bb:.0f})")
                elif avg_bb >= 50:
                    recovery_score += 10
                    recovery_factors.append(f"Good battery ({avg_bb:.0f})")
                else:
                    recovery_factors.append(f"Low battery ({avg_bb:.0f})")

            # Stress
            if metrics["stress_avg"]:
                avg_stress = sum(metrics["stress_avg"]) / len(metrics["stress_avg"])
                if avg_stress <= 30:
                    recovery_score += 10
                    recovery_factors.append(f"Low stress ({avg_stress:.0f})")
                else:
                    recovery_factors.append(f"Elevated stress ({avg_stress:.0f})")

            recovery_status = "excellent" if recovery_score >= 80 else \
                             "good" if recovery_score >= 60 else \
                             "fair" if recovery_score >= 40 else "poor"

            return {
                "athlete_id": athlete_id,
                "as_of": datetime.now().isoformat(),
                "recovery_score": min(recovery_score, 100),
                "recovery_status": recovery_status,
                "factors": recovery_factors,
                "latest_wellness": {
                    "date": wellness[-1].date if wellness else None,
                    "hrv_rmssd": wellness[-1].hrv_rmssd if wellness else None,
                    "resting_hr": wellness[-1].resting_hr if wellness else None,
                    "sleep_hours": wellness[-1].sleep_hours if wellness else None,
                    "body_battery": wellness[-1].body_battery_end if wellness else None,
                },
            }

        except Exception as e:
            logger.error("Failed to get recovery status: %s", e)
            raise


def _overtraining_recommendation(risk_score: float, risk_factors: list[str]) -> str:
    """Generate a recommendation based on overtraining risk."""
    if risk_score < 0.4:
        return "Training stress is well-managed. Continue with current program."
    elif risk_score < 0.7:
        return f"Caution: {len(risk_factors)} risk factors detected. Consider reducing intensity or volume."
    else:
        return (
            f"WARNING: High overtraining risk ({risk_score:.0%}). "
            f"Reduce training load, increase recovery focus. {risk_factors[0] if risk_factors else ''}"
        )
