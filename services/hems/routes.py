"""HEMS API routes."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from config import HEMSMode, HEMSSettings

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
