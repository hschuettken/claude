"""HEMS API routes."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, time as dt_time, timezone
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
    """
    write_api = request.app.state.influxdb_write_api
    settings: HEMSSettings = request.app.state.settings

    if not write_api:
        logger.warning("InfluxDB not available — thermal log discarded")
        return {"status": "skipped", "reason": "InfluxDB not available"}

    try:
        import influxdb_client

        point = (
            influxdb_client.Point("thermal_training")
            .tag("room_id", body.room_id)
            .field("measured_temp", body.measured_temp)
            .field("target_temp", body.target_temp)
            .field("valve_position_pct", body.valve_pos)
        )

        if body.outdoor_temp is not None:
            point = point.field("outdoor_temp", body.outdoor_temp)

        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)

        logger.debug(
            "Logged thermal data: room=%s, measured=%.1f°C, target=%.1f°C, valve=%.1f%%",
            body.room_id,
            body.measured_temp,
            body.target_temp,
            body.valve_pos,
        )

        return {"status": "logged", "measurement": "thermal_training", "room": body.room_id}

    except Exception as e:
        logger.error("Failed to log thermal data: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to log thermal data: {e}")
