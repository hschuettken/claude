"""Pydantic schemas for energy domain NATS events.

All events are published to NATS with the subject as the topic name.
Events are JSON-serialized (model.model_dump_json()).
"""

from __future__ import annotations


from pydantic import BaseModel


# ---------------------------------------------------------------------------
# PV Forecast events
# ---------------------------------------------------------------------------


class PVForecastUpdated(BaseModel):
    """energy.pv.forecast_updated"""

    today_kwh: float
    today_remaining_kwh: float
    tomorrow_kwh: float
    day_after_kwh: float
    east_today_kwh: float
    west_today_kwh: float
    confidence: float  # 0.0-1.0 based on model R²
    model_type: str  # "ml" or "fallback"
    timestamp: str  # ISO format
    sunrise: str | None = None  # HH:MM local time
    sunset: str | None = None  # HH:MM local time


class PVModelRetrained(BaseModel):
    """energy.pv.model_retrained"""

    east_r2: float
    east_mae: float
    west_r2: float
    west_mae: float
    east_data_days: int
    west_data_days: int
    timestamp: str


class PVAnomalyDetected(BaseModel):
    """energy.pv.anomaly_detected"""

    array: str  # "east" or "west"
    actual_kwh: float
    forecast_kwh: float
    deviation_pct: float
    timestamp: str


class PVDriftDetected(BaseModel):
    """energy.pv.drift_detected"""

    mae_7d: float
    mae_30d: float
    ratio: float
    threshold: float
    timestamp: str


class SolarDaylightWindow(BaseModel):
    """energy.solar.daylight_window"""

    sunrise: str  # ISO datetime
    sunset: str  # ISO datetime
    sunrise_hhmm: str  # HH:MM local time
    sunset_hhmm: str  # HH:MM local time
    date: str  # YYYY-MM-DD
    timestamp: str


class PVForecastAccuracyResult(BaseModel):
    """Published after accuracy check, subject: energy.pv.accuracy_checked"""

    date: str  # YYYY-MM-DD
    east_forecast_kwh: float
    east_actual_kwh: float
    east_delta_pct: float
    west_forecast_kwh: float
    west_actual_kwh: float
    west_delta_pct: float
    total_forecast_kwh: float
    total_actual_kwh: float
    total_delta_pct: float
    accuracy_pct: float  # 100 - abs(total_delta_pct), floored at 0
    timestamp: str


# ---------------------------------------------------------------------------
# EV events
# ---------------------------------------------------------------------------


class EVPlanUpdated(BaseModel):
    """energy.ev.plan_updated"""

    trace_id: str
    days: list[dict]  # DayChargingRecommendation dicts
    urgency: str  # none/low/medium/high/critical
    mode: str
    timestamp: str
    current_soc_pct: float | None = None  # EV SoC at time of plan generation


class EVChargingStarted(BaseModel):
    """energy.ev.charging_started"""

    mode: str
    target_kwh: float
    target_soc: float | None = None
    timestamp: str


class EVChargingCompleted(BaseModel):
    """energy.ev.charging_completed"""

    session_kwh: float
    duration_minutes: float
    pv_fraction: float  # 0.0-1.0
    grid_fraction: float  # 0.0-1.0
    battery_assist_kwh: float
    cost_estimate_eur: float
    timestamp: str


class EVModeChanged(BaseModel):
    """energy.ev.mode_changed"""

    old_mode: str
    new_mode: str
    reason: str
    timestamp: str


class EVSurplusAvailable(BaseModel):
    """energy.ev.surplus_available"""

    pv_w: float
    battery_soc: float
    ev_soc: float | None = None
    surplus_w: float
    timestamp: str


class EVDrainStarted(BaseModel):
    """energy.ev.drain_started"""

    drain_budget_kwh: float
    battery_soc_pct: float
    pv_remaining_kwh: float
    timestamp: str


class EVDrainBudgetExhausted(BaseModel):
    """energy.ev.drain_budget_exhausted"""

    kwh_drained: float
    budget_kwh: float
    battery_soc_pct: float
    timestamp: str


class EVDrainRefillComplete(BaseModel):
    """energy.ev.drain_refill_complete"""

    battery_soc_pct: float
    refill_duration_minutes: float
    timestamp: str
