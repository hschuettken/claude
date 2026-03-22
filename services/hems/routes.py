"""HEMS API routes."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, time as dt_time, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from config import HEMSMode, HEMSSettings
from database import HEMSDatabase

logger = logging.getLogger("hems.routes")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"


class StatusResponse(BaseModel):
    service: str = "hems"
    mode: HEMSMode
    uptime_seconds: float
    timestamp: str


class ScheduleEntry(BaseModel):
    id: Optional[str] = None
    device: str = Field(..., description="Device/load identifier, e.g. 'ev_charger', 'boiler'")
    start_time: str = Field(..., description="ISO-8601 datetime")
    end_time: str = Field(..., description="ISO-8601 datetime")
    power_kw: float = Field(..., description="Target power in kW")
    priority: int = Field(default=5, ge=1, le=10, description="1=low, 10=high")
    notes: Optional[str] = None


class ScheduleResponse(BaseModel):
    schedules: list[ScheduleEntry]
    count: int


class ScheduleCreateResponse(BaseModel):
    id: str
    message: str


class ModeResponse(BaseModel):
    mode: HEMSMode


class ModeSetRequest(BaseModel):
    mode: HEMSMode


class ScheduleCreateRequest(BaseModel):
    room_id: str = Field(..., description="Room identifier (e.g., 'living_room')")
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: str = Field(..., description="Time in HH:MM:SS format")
    end_time: str = Field(..., description="Time in HH:MM:SS format")
    target_temp: float = Field(..., ge=5, le=40, description="Target temperature in °C")
    mode: str = Field(default="comfort", description="Mode: comfort, eco, off, etc.")
    active: bool = Field(default=True)


class ScheduleUpdateRequest(BaseModel):
    target_temp: Optional[float] = Field(None, ge=5, le=40)
    mode: Optional[str] = None
    active: Optional[bool] = None


class ScheduleItem(BaseModel):
    id: UUID
    room_id: str
    day_of_week: int
    start_time: dt_time
    end_time: dt_time
    target_temp: float
    mode: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ScheduleCurrentResponse(BaseModel):
    room_id: str
    target_temp: float
    mode: str
    timestamp: str


class ThermalLogRequest(BaseModel):
    room_id: str = Field(..., description="Room identifier")
    measured_temp: float = Field(..., description="Measured temperature in °C")
    target_temp: float = Field(..., description="Target temperature in °C")
    outdoor_temp: Optional[float] = Field(None, description="Outdoor temperature in °C")
    valve_pos: float = Field(..., ge=0, le=100, description="Valve position 0-100%")


# ============================================================================
# Phase 3: Thermal Training Data Collection & Predictive Heating
# ============================================================================


class ThermalTrainingSnapshot(BaseModel):
    """Snapshot of current thermal state for training data collection."""
    room_id: str = Field(..., description="Room identifier")
    outside_temp: Optional[float] = Field(None, description="Outside temperature in °C")
    flow_temp: float = Field(..., description="Flow temperature in °C")
    return_temp: Optional[float] = Field(None, description="Return temperature in °C")
    room_temp: float = Field(..., description="Room temperature in °C")
    setpoint: float = Field(..., description="Current setpoint in °C")
    actual_heating: bool = Field(..., description="Whether heating is currently active")
    weather_condition: Optional[str] = Field(None, description="Current weather condition")


class SetpointPredictionRequest(BaseModel):
    """Request for predicted setpoint based on lead time."""
    room_id: str = Field(..., description="Room identifier")
    target_temp: float = Field(..., ge=5, le=40, description="Desired target temperature in °C")
    lead_time_minutes: int = Field(..., ge=1, description="Minutes ahead to predict")


class SetpointPredictionResponse(BaseModel):
    """Predicted setpoint for optimal heating control."""
    predicted_setpoint: float = Field(..., description="Predicted setpoint in °C")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score 0-1")
    method: str = Field(..., description="Prediction method: 'rule_based' or 'ml'")
    notes: str = Field(..., description="Explanation of prediction")
    timestamp: str = Field(..., description="Timestamp of prediction")


class ThermalTrainingExportResponse(BaseModel):
    """Exported thermal training data."""
    data: list[dict] = Field(..., description="Array of training data points")
    count: int = Field(..., description="Number of data points")
    period_days: int = Field(..., description="Period covered in days")
    from_timestamp: str = Field(..., description="Start timestamp")
    to_timestamp: str = Field(..., description="End timestamp")


# ---------------------------------------------------------------------------
# In-memory state (replace with DB in production)
# ---------------------------------------------------------------------------

_start_time = time.monotonic()
_schedules: list[dict[str, Any]] = []
_schedule_counter = 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/api/v1/hems/status", response_model=StatusResponse, tags=["hems"])
async def get_status(request: Request) -> StatusResponse:
    settings: HEMSSettings = request.app.state.settings
    return StatusResponse(
        service="hems",
        mode=settings.hems_mode,
        uptime_seconds=round(time.monotonic() - _start_time, 1),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api/v1/hems/schedule", response_model=ScheduleResponse, tags=["hems"])
async def get_schedules() -> ScheduleResponse:
    entries = [ScheduleEntry(**s) for s in _schedules]
    return ScheduleResponse(schedules=entries, count=len(entries))


@router.post(
    "/api/v1/hems/schedule",
    response_model=ScheduleCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["hems"],
)
async def create_schedule(entry: ScheduleEntry, request: Request) -> ScheduleCreateResponse:
    global _schedule_counter
    settings: HEMSSettings = request.app.state.settings

    if settings.hems_mode == HEMSMode.off:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HEMS is in 'off' mode — scheduling disabled",
        )

    _schedule_counter += 1
    entry_id = f"sched-{_schedule_counter:04d}"
    record = entry.model_dump()
    record["id"] = entry_id
    _schedules.append(record)

    logger.info("Schedule created: %s device=%s", entry_id, entry.device)
    return ScheduleCreateResponse(id=entry_id, message="Schedule created")


@router.get("/api/v1/hems/mode", response_model=ModeResponse, tags=["hems"])
async def get_mode(request: Request) -> ModeResponse:
    settings: HEMSSettings = request.app.state.settings
    return ModeResponse(mode=settings.hems_mode)


@router.post("/api/v1/hems/mode", response_model=ModeResponse, tags=["hems"])
async def set_mode(body: ModeSetRequest, request: Request) -> ModeResponse:
    settings: HEMSSettings = request.app.state.settings
    old_mode = settings.hems_mode
    settings.hems_mode = body.mode
    logger.info("Mode changed: %s → %s", old_mode, body.mode)
    return ModeResponse(mode=settings.hems_mode)


# ============================================================================
# Schedule Management (Phase 1)
# ============================================================================


@router.get("/api/v1/hems/schedule", response_model=list[ScheduleItem], tags=["hems"])
async def list_schedules(room_id: Optional[str] = None, request: Request = None) -> list[ScheduleItem]:
    """List all schedules, optionally filtered by room."""
    db: Optional[HEMSDatabase] = request.app.state.db
    if not db:
        logger.warning("Database not available for schedule listing")
        return []
    
    records = await db.list_schedules(room_id=room_id)
    return [
        ScheduleItem(
            id=r.id,
            room_id=r.room_id,
            day_of_week=r.day_of_week,
            start_time=r.start_time,
            end_time=r.end_time,
            target_temp=r.target_temp,
            mode=r.mode,
            active=r.active,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in records
    ]


@router.post("/api/v1/hems/schedule", status_code=status.HTTP_201_CREATED, tags=["hems"])
async def create_schedule(body: ScheduleCreateRequest, request: Request) -> ScheduleItem:
    """Create a new climate schedule."""
    db: Optional[HEMSDatabase] = request.app.state.db
    
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

    # Parse times
    try:
        start = dt_time.fromisoformat(body.start_time)
        end = dt_time.fromisoformat(body.end_time)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid time format: {e}")

    record = await db.create_schedule(
        room_id=body.room_id,
        day_of_week=body.day_of_week,
        start_time=start,
        end_time=end,
        target_temp=body.target_temp,
        mode=body.mode,
        active=body.active,
    )

    if not record:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create schedule")

    logger.info("Schedule created: room=%s, dow=%d, time=%s-%s, temp=%.1f°C", body.room_id, body.day_of_week, start, end, body.target_temp)

    return ScheduleItem(
        id=record.id,
        room_id=record.room_id,
        day_of_week=record.day_of_week,
        start_time=record.start_time,
        end_time=record.end_time,
        target_temp=record.target_temp,
        mode=record.mode,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/api/v1/hems/schedule/{schedule_id}", response_model=ScheduleItem, tags=["hems"])
async def get_schedule(schedule_id: UUID, request: Request) -> ScheduleItem:
    """Fetch a single schedule by ID."""
    db: Optional[HEMSDatabase] = request.app.state.db
    
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    
    record = await db.get_schedule(schedule_id)

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    return ScheduleItem(
        id=record.id,
        room_id=record.room_id,
        day_of_week=record.day_of_week,
        start_time=record.start_time,
        end_time=record.end_time,
        target_temp=record.target_temp,
        mode=record.mode,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.patch("/api/v1/hems/schedule/{schedule_id}", response_model=ScheduleItem, tags=["hems"])
async def update_schedule(schedule_id: UUID, body: ScheduleUpdateRequest, request: Request) -> ScheduleItem:
    """Update a schedule (target temp, mode, or active status)."""
    db: Optional[HEMSDatabase] = request.app.state.db
    
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

    record = await db.update_schedule(
        schedule_id=schedule_id,
        target_temp=body.target_temp,
        mode=body.mode,
        active=body.active,
    )

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    return ScheduleItem(
        id=record.id,
        room_id=record.room_id,
        day_of_week=record.day_of_week,
        start_time=record.start_time,
        end_time=record.end_time,
        target_temp=record.target_temp,
        mode=record.mode,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/api/v1/hems/schedule/{room_id}/current", response_model=ScheduleCurrentResponse, tags=["hems"])
async def get_current_schedule(room_id: str, request: Request) -> ScheduleCurrentResponse:
    """Get the current active schedule for a room (based on current day/time)."""
    db: Optional[HEMSDatabase] = request.app.state.db
    
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=Monday, 6=Sunday
    current_time = now.time()

    record = await db.get_current_schedule(room_id=room_id, dow=dow, current_time=current_time)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active schedule found for room {room_id}",
        )

    return ScheduleCurrentResponse(
        room_id=record.room_id,
        target_temp=record.target_temp,
        mode=record.mode,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ============================================================================
# Thermal Data Logging (Phase 1 - InfluxDB)
# ============================================================================


@router.post("/api/v1/hems/thermal/log", status_code=status.HTTP_202_ACCEPTED, tags=["hems"])
async def log_thermal_data(body: ThermalLogRequest, request: Request) -> dict[str, str]:
    """Log thermal training data to InfluxDB.

    This endpoint accepts room temperature, target, outdoor conditions,
    and valve position for thermal model training and analysis.
    
    Handles None/NaN values gracefully by skipping invalid fields.
    """
    write_api = request.app.state.influxdb_write_api
    settings: HEMSSettings = request.app.state.settings

    if not write_api:
        logger.warning("InfluxDB not available — thermal log discarded")
        return {"status": "skipped", "reason": "InfluxDB not available"}

    try:
        import influxdb_client
        import math

        # Validate numeric values
        measured_temp = body.measured_temp
        target_temp = body.target_temp
        valve_pos = body.valve_pos
        outdoor_temp = body.outdoor_temp

        # Skip if any critical value is invalid
        if (measured_temp is None or math.isnan(measured_temp) or
            target_temp is None or math.isnan(target_temp) or
            valve_pos is None or math.isnan(valve_pos)):
            logger.warning(
                f"Skipping thermal log for {body.room_id}: invalid values "
                f"(measured={measured_temp}, target={target_temp}, valve={valve_pos})"
            )
            return {
                "status": "skipped",
                "reason": "Invalid temperature or valve data",
                "room": body.room_id
            }

        point = (
            influxdb_client.Point("thermal_training")
            .tag("room_id", body.room_id)
            .field("measured_temp", float(measured_temp))
            .field("target_temp", float(target_temp))
            .field("valve_position_pct", float(valve_pos))
        )

        # Optional outdoor temperature
        if outdoor_temp is not None and not math.isnan(outdoor_temp):
            point = point.field("outdoor_temp", float(outdoor_temp))

        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)

        logger.debug(
            "Logged thermal data: room=%s, measured=%.1f°C, target=%.1f°C, valve=%.1f%%",
            body.room_id,
            measured_temp,
            target_temp,
            valve_pos,
        )

        return {"status": "logged", "measurement": "thermal_training", "room": body.room_id}

    except Exception as e:
        logger.error("Failed to log thermal data: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to log thermal data: {e}")


# ============================================================================
# Phase 3: Thermal Training Data Collection & Predictive Heating
# ============================================================================


@router.post("/api/v1/hems/thermal-training/snapshot", status_code=status.HTTP_200_OK, tags=["hems"])
async def thermal_training_snapshot(body: ThermalTrainingSnapshot, request: Request) -> dict[str, str]:
    """Manually capture a thermal training data snapshot.

    Records current thermal state (room temp, flow temp, setpoint, etc.)
    to InfluxDB thermal_training measurement for ML model training.
    
    Endpoint: POST /api/v1/hems/thermal-training/snapshot
    
    This can be called manually for immediate capture, and is also called
    automatically by the periodic thermal data collector (every 15 min).
    """
    write_api = request.app.state.influxdb_write_api
    settings: HEMSSettings = request.app.state.settings

    if not write_api:
        logger.warning("InfluxDB not available — thermal snapshot discarded")
        return {"status": "skipped", "reason": "InfluxDB not available"}

    try:
        import influxdb_client

        point = (
            influxdb_client.Point("thermal_training")
            .tag("room_id", body.room_id)
            .field("flow_temp", float(body.flow_temp))
            .field("room_temp", float(body.room_temp))
            .field("setpoint", float(body.setpoint))
            .field("actual_heating", body.actual_heating)
        )

        # Optional fields
        if body.outside_temp is not None:
            point = point.field("outside_temp", float(body.outside_temp))
        if body.return_temp is not None:
            point = point.field("return_temp", float(body.return_temp))
        if body.weather_condition is not None:
            point = point.tag("weather_condition", body.weather_condition)

        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)

        logger.info(
            "Thermal training snapshot: room=%s, flow=%.1f°C, room=%.1f°C, sp=%.1f°C, heating=%s",
            body.room_id,
            body.flow_temp,
            body.room_temp,
            body.setpoint,
            body.actual_heating,
        )

        return {
            "status": "captured",
            "measurement": "thermal_training",
            "room": body.room_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Failed to capture thermal snapshot: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to capture snapshot: {e}")


@router.get("/api/v1/hems/predict/setpoint", response_model=SetpointPredictionResponse, tags=["hems"])
async def predict_setpoint(
    room_id: str,
    target_temp: float,
    lead_time_minutes: int,
    request: Request,
) -> SetpointPredictionResponse:
    """Predict optimal setpoint for heating based on lead time.

    Endpoint: GET /api/v1/hems/predict/setpoint?room_id={id}&target_temp={t}&lead_time_minutes={n}
    
    For now (Phase 3): returns rule-based prediction.
    Real ML model will replace this when >30 days of training data exists.
    
    Args:
        room_id: Room identifier
        target_temp: Desired target temperature (°C)
        lead_time_minutes: Minutes ahead to predict
    
    Returns:
        SetpointPredictionResponse with predicted setpoint and confidence
    """
    logger.info(
        "Setpoint prediction: room=%s, target=%.1f°C, lead_time=%d min",
        room_id,
        target_temp,
        lead_time_minutes,
    )

    # Phase 3: Simple rule-based prediction
    # TODO: Replace with ML model when training data is sufficient
    predicted_setpoint = target_temp
    confidence = 0.5
    method = "rule_based"
    notes = "Rule-based prediction: no ML model yet"

    if lead_time_minutes > 120:
        # Very long lead time — reduce setpoint to avoid overshoot
        predicted_setpoint = target_temp - 2.0
        notes = f"Very long lead time ({lead_time_minutes}min) — reducing setpoint by 2°C to minimize overshoot"
    elif lead_time_minutes > 60:
        # Long lead time — slightly reduce setpoint
        predicted_setpoint = target_temp - 1.0
        notes = f"Long lead time ({lead_time_minutes}min) — reducing setpoint by 1°C"
    else:
        # Short lead time — use target directly
        predicted_setpoint = target_temp
        notes = f"Short lead time ({lead_time_minutes}min) — using target setpoint directly"

    # Clamp to valid range
    predicted_setpoint = max(5.0, min(40.0, predicted_setpoint))

    return SetpointPredictionResponse(
        predicted_setpoint=predicted_setpoint,
        confidence=confidence,
        method=method,
        notes=notes,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api/v1/hems/thermal-training/export", response_model=ThermalTrainingExportResponse, tags=["hems"])
async def export_thermal_training(
    days: int = 7,
    request: Request = None,
) -> ThermalTrainingExportResponse:
    """Export thermal training data from InfluxDB for ML pipeline.

    Endpoint: GET /api/v1/hems/thermal-training/export?days=7
    
    Returns: Array of thermal training data points from the last N days.
    
    Args:
        days: Number of days of data to export (default 7)
    
    Returns:
        ThermalTrainingExportResponse with training data array and metadata
    """
    settings: HEMSSettings = request.app.state.settings
    influxdb_client_instance = request.app.state.influxdb_client
    
    if not influxdb_client_instance:
        logger.warning("InfluxDB not available — cannot export training data")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="InfluxDB not available"
        )

    try:
        import influxdb_client

        # Create query API
        query_api = influxdb_client_instance.query_api()

        # Build Flux query for last N days
        now = datetime.now(timezone.utc)
        from_time = now - timedelta(days=days)

        flux_query = f"""
        from(bucket: "{settings.influxdb_bucket}")
          |> range(start: {from_time.isoformat()}, stop: {now.isoformat()})
          |> filter(fn: (r) => r._measurement == "thermal_training")
          |> sort(columns: ["_time"])
        """

        # Execute query
        tables = query_api.query(flux_query, org=settings.influxdb_org)

        # Parse results into data array
        data = []
        for table in tables:
            for record in table.records:
                data_point = {
                    "timestamp": record.get_time().isoformat() if record.get_time() else None,
                    "room_id": record.tags.get("room_id") if record.tags else None,
                    "weather_condition": record.tags.get("weather_condition") if record.tags else None,
                    "field": record.field,
                    "value": record.value,
                }
                data.append(data_point)

        logger.info("Exported %d thermal training data points (last %d days)", len(data), days)

        return ThermalTrainingExportResponse(
            data=data,
            count=len(data),
            period_days=days,
            from_timestamp=from_time.isoformat(),
            to_timestamp=now.isoformat(),
        )

    except Exception as e:
        logger.error("Failed to export thermal training data: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export training data: {e}"
        )


# ---------------------------------------------------------------------------
# Thermal model endpoints (Phase 3)
# ---------------------------------------------------------------------------

class ThermalModelResponse(BaseModel):
    room_id: str
    u_eff: float = Field(..., description="Effective heat-loss coefficient W/K")
    thermal_capacity: float = Field(..., description="Room thermal capacity Wh/K")
    fitted_at: Optional[str] = None
    source: str = "default"


class ThermalModelFitResponse(BaseModel):
    room_id: str
    u_eff: float
    thermal_capacity: float
    fitted_at: str
    training_rows: int
    message: str


@router.get(
    "/api/v1/hems/rooms/{room_id}/thermal-model",
    response_model=ThermalModelResponse,
    tags=["hems"],
)
async def get_thermal_model(room_id: str, request: Request) -> ThermalModelResponse:
    """Return current physics model parameters for a room."""
    from thermal_model import PhysicsModel, PhysicsModelParams, DEFAULT_U_EFF, DEFAULT_CAPACITY

    db: HEMSDatabase = request.app.state.db
    config_key = f"physics_model_{room_id}"
    raw = await db.get_config(config_key)

    if raw:
        try:
            model = PhysicsModel.from_json(room_id, raw)
            p = model.params
            return ThermalModelResponse(
                room_id=room_id,
                u_eff=p.u_eff,
                thermal_capacity=p.thermal_capacity,
                fitted_at=p.fitted_at,
                source="fitted",
            )
        except Exception as e:
            logger.warning("Failed to parse thermal model for %s: %s", room_id, e)

    return ThermalModelResponse(
        room_id=room_id,
        u_eff=DEFAULT_U_EFF,
        thermal_capacity=DEFAULT_CAPACITY,
        fitted_at=None,
        source="default",
    )


@router.post(
    "/api/v1/hems/rooms/{room_id}/thermal-model/fit",
    response_model=ThermalModelFitResponse,
    tags=["hems"],
)
async def fit_thermal_model(room_id: str, request: Request) -> ThermalModelFitResponse:
    """Fit physics model parameters from stored training data and persist."""
    from thermal_model import PhysicsModel

    db: HEMSDatabase = request.app.state.db

    # --- Fetch training data from InfluxDB (last 7 days) ---
    training_rows: list[dict] = []
    try:
        influxdb_client_instance = request.app.state.influxdb_client
        settings: HEMSSettings = request.app.state.settings

        if influxdb_client_instance:
            import influxdb_client as _ic  # noqa: F401
            from datetime import timedelta

            query_api = influxdb_client_instance.query_api()
            now = datetime.now(timezone.utc)
            from_time = now - timedelta(days=7)

            flux = f"""
            from(bucket: "{settings.influxdb_bucket}")
              |> range(start: {from_time.isoformat()}, stop: {now.isoformat()})
              |> filter(fn: (r) => r._measurement == "thermal_training")
              |> filter(fn: (r) => r["room_id"] == "{room_id}")
              |> sort(columns: ["_time"])
            """
            tables = query_api.query(flux, org=settings.influxdb_org)

            # Pivot field values into dicts by timestamp
            by_ts: dict[str, dict] = {}
            for table in tables:
                for record in table.records:
                    ts = record.get_time().isoformat() if record.get_time() else "?"
                    row = by_ts.setdefault(ts, {})
                    row[record.field] = record.value

            for row in by_ts.values():
                if all(k in row for k in ("flow_temp", "outdoor_temp", "room_temp")):
                    training_rows.append({
                        "flow_temp": row["flow_temp"],
                        "outdoor_temp": row["outdoor_temp"],
                        "room_temp_before": row["room_temp"],
                        "room_temp_after": row.get("room_temp_after", row["room_temp"]),
                        "dt_minutes": 15.0,
                    })
    except Exception as exc:
        logger.warning("Failed to load training data from InfluxDB for %s: %s", room_id, exc)

    # --- Fit model ---
    model = PhysicsModel(room_id=room_id)
    params = model.fit_parameters(training_rows)

    # --- Persist to DB ---
    config_key = f"physics_model_{room_id}"
    await db.set_config(config_key, model.to_json())

    return ThermalModelFitResponse(
        room_id=room_id,
        u_eff=params.u_eff,
        thermal_capacity=params.thermal_capacity,
        fitted_at=params.fitted_at or datetime.now(timezone.utc).isoformat(),
        training_rows=len(training_rows),
        message=f"Fitted with {len(training_rows)} training rows" if training_rows else "No training data — defaults saved",
    )


# ============================================================================
# Phase 4: Adaptive Heating Schedules
# ============================================================================

class AdaptiveScheduleSlot(BaseModel):
    """Single 15-min schedule slot."""
    time: str = Field(..., description="ISO-8601 datetime")
    room_id: str = Field(..., description="Room identifier")
    target_temp: float = Field(..., description="Target temperature (°C)")
    mode: str = Field(..., description="Mode: comfort, eco, off")


class AdaptiveScheduleGenerateRequest(BaseModel):
    """Request to generate adaptive schedule."""
    room_id: str = Field(..., description="Room identifier")
    comfort_temp: float = Field(default=21.0, ge=5, le=40, description="Comfort setpoint (°C)")
    setback_temp: float = Field(default=16.0, ge=5, le=40, description="Away setpoint (°C)")
    occupancy_hints: Optional[list[dict]] = Field(
        default=None,
        description="List of {start_time, end_time} occupancy windows (HH:MM:SS format)"
    )
    weather_forecast: Optional[dict] = Field(
        default=None,
        description="Weather forecast: {temp: float, condition: str}"
    )


class AdaptiveScheduleGenerateResponse(BaseModel):
    """Response from adaptive schedule generation."""
    room_id: str
    schedule: list[AdaptiveScheduleSlot]
    count: int = Field(..., description="Number of intervals")
    start_time: str = Field(..., description="Start of 24h period")
    end_time: str = Field(..., description="End of 24h period")
    message: str


class AdaptiveScheduleResponse(BaseModel):
    """Today's adaptive schedule."""
    room_id: str
    schedule: list[AdaptiveScheduleSlot]
    count: int
    date: str


@router.post("/api/v1/hems/schedule/adaptive", response_model=AdaptiveScheduleGenerateResponse, tags=["hems-phase4"])
async def generate_adaptive_schedule(
    body: AdaptiveScheduleGenerateRequest,
    request: Request,
) -> AdaptiveScheduleGenerateResponse:
    """Generate adaptive 24h heating schedule.

    Endpoint: POST /api/v1/hems/schedule/adaptive
    
    Inputs:
      - room_id: Room identifier
      - comfort_temp: Target temp when occupied (°C)
      - setback_temp: Target temp when away (°C)
      - occupancy_hints: List of occupied time windows (optional)
      - weather_forecast: Current weather (optional)
    
    Algorithm:
      1. For each 15-min slot in next 24h:
         - Check if occupied (via occupancy_hints or defaults)
         - If occupied: use comfort_temp
         - If away: use setback_temp
         - Apply weather boost if cold
      2. Store schedule in DB
      3. Return slots for frontend display
    """
    db: Optional[HEMSDatabase] = request.app.state.db
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

    try:
        from adaptive_schedule import AdaptiveScheduleGenerator, AdaptiveScheduleRequest

        # Build request for generator
        occupancy = None
        if body.occupancy_hints:
            # Convert {start_time, end_time} strings to time objects
            occupancy = []
            for hint in body.occupancy_hints:
                start_str = hint.get("start_time", "07:00:00")
                end_str = hint.get("end_time", "23:00:00")
                try:
                    start = dt_time.fromisoformat(start_str)
                    end = dt_time.fromisoformat(end_str)
                    occupancy.append((start, end))
                except ValueError:
                    logger.warning("Invalid occupancy time: %s-%s", start_str, end_str)

        req = AdaptiveScheduleRequest(
            room_id=body.room_id,
            comfort_temp=body.comfort_temp,
            setback_temp=body.setback_temp,
            weather_forecast=body.weather_forecast,
            occupancy_hints=occupancy,
        )

        # Generate schedule
        generator = AdaptiveScheduleGenerator()
        intervals = generator.generate(req)

        # Store to DB
        interval_dicts = [i.to_dict() for i in intervals]
        success = await db.store_adaptive_schedule(body.room_id, interval_dicts)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store adaptive schedule"
            )

        # Return response
        slots = [
            AdaptiveScheduleSlot(
                time=i.time.isoformat(),
                room_id=i.room_id,
                target_temp=i.target_temp,
                mode=i.mode,
            )
            for i in intervals
        ]

        start_time = intervals[0].time if intervals else datetime.now(timezone.utc)
        end_time = intervals[-1].time if intervals else datetime.now(timezone.utc)

        logger.info(
            "Generated adaptive schedule: room=%s, %d intervals, stored to DB",
            body.room_id,
            len(intervals),
        )

        return AdaptiveScheduleGenerateResponse(
            room_id=body.room_id,
            schedule=slots,
            count=len(slots),
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            message=f"Generated {len(slots)} 15-min schedule slots for next 24h",
        )

    except Exception as e:
        logger.error("Failed to generate adaptive schedule: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate schedule: {e}"
        )


@router.get("/api/v1/hems/schedule/today", response_model=AdaptiveScheduleResponse, tags=["hems-phase4"])
async def get_today_adaptive_schedule(
    room_id: str,
    request: Request,
) -> AdaptiveScheduleResponse:
    """Fetch today's adaptive schedule for a room.

    Endpoint: GET /api/v1/hems/schedule/today?room_id={room_id}
    
    Returns: List of schedule slots for today (UTC date).
    """
    db: Optional[HEMSDatabase] = request.app.state.db
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )

    try:
        schedule_dicts = await db.get_today_adaptive_schedule(room_id)

        slots = [
            AdaptiveScheduleSlot(
                time=s["time_slot"],
                room_id=s["room_id"],
                target_temp=s["target_temp"],
                mode=s["mode"],
            )
            for s in schedule_dicts
        ]

        today = datetime.now(timezone.utc).date().isoformat()

        logger.info(
            "Fetched today's adaptive schedule: room=%s, %d slots",
            room_id,
            len(slots),
        )

        return AdaptiveScheduleResponse(
            room_id=room_id,
            schedule=slots,
            count=len(slots),
            date=today,
        )

    except Exception as e:
        logger.error("Failed to fetch adaptive schedule: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch schedule: {e}"
        )
