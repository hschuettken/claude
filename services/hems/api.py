"""HEMS Phase 2 Internal API - Advanced Analytics & Control Endpoints.

This module provides internal API endpoints for:
1. Energy consumption analytics (hourly/daily/monthly breakdown)
2. Thermal analytics (room temps, boiler runtime, PV utilization)
3. Neural network model status & retraining
4. Boiler state queries
5. Control decision history
6. Manual flow temp overrides

All endpoints are async and optimized for InfluxDB + PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
import asyncpg
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from influxdb_client.client.query_api import QueryApi

logger = logging.getLogger("hems.api")

router = APIRouter(prefix="/api", tags=["internal"])


# ============================================================================
# Pydantic Models
# ============================================================================

class EnergyBreakdown(BaseModel):
    """Energy consumption breakdown by source."""

    boiler: float = Field(..., description="Boiler energy (kWh)")
    circulation_pump: float = Field(..., description="Circulation pump energy (kWh)")
    supplemental_heat: float = Field(..., description="Supplemental heating energy (kWh)")
    pv_exported: float = Field(..., description="PV energy exported to grid (kWh)")
    pv_used: float = Field(..., description="PV energy used directly (kWh)")


class EnergyResponse(BaseModel):
    """Energy consumption response with breakdown."""

    total_consumed_kwh: float = Field(..., description="Total energy consumed (kWh)")
    period: str = Field(..., description="Time period (hour/day/month)")
    period_start: str = Field(..., description="ISO-8601 period start")
    period_end: str = Field(..., description="ISO-8601 period end")
    breakdown: EnergyBreakdown
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class ThermalStats(BaseModel):
    """Thermal system statistics."""

    avg_room_temp_c: float = Field(..., description="Average room temperature (°C)")
    current_room_temp_c: float = Field(..., description="Current room temperature (°C)")
    avg_setpoint_c: float = Field(..., description="Average setpoint temperature (°C)")
    boiler_runtime_minutes: float = Field(..., description="Boiler runtime in period (minutes)")
    boiler_on_duty_cycle: float = Field(..., description="Boiler on-time as % of period (0-100)")
    pv_utilization_percent: float = Field(..., description="PV utilization % (0-100)")
    mixing_valve_avg_position: float = Field(..., description="Mixing valve avg position (0-100)")


class AnalyticsResponse(BaseModel):
    """Analytics response for a period."""

    period: str = Field(..., description="Period (hour/day/week/month)")
    period_start: str = Field(..., description="ISO-8601 period start")
    period_end: str = Field(..., description="ISO-8601 period end")
    thermal_stats: ThermalStats
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class ModelStatus(str, Enum):
    """Neural network model status."""

    IDLE = "idle"
    TRAINING = "training"
    RETRAINING = "retraining"
    READY = "ready"
    ERROR = "error"


class ModelStatusResponse(BaseModel):
    """NN model status response."""

    status: ModelStatus = Field(..., description="Current model status")
    model_id: str = Field(..., description="Model identifier")
    last_trained: str = Field(..., description="ISO-8601 last training timestamp")
    training_loss: Optional[float] = Field(None, description="Last training loss value")
    accuracy: Optional[float] = Field(None, description="Model accuracy (0-1)")
    retraining_progress: Optional[float] = Field(None, description="Retraining progress (0-1)")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class RetrainRequest(BaseModel):
    """Request to retrain the NN model."""

    include_recent_data: bool = Field(default=True, description="Include last 24h data")
    epochs: int = Field(default=50, ge=1, le=500, description="Training epochs")
    batch_size: int = Field(default=32, ge=1, le=256, description="Batch size")


class RetrainResponse(BaseModel):
    """Response to retraining request."""

    job_id: str = Field(..., description="Async job ID")
    status: str = Field(default="queued", description="Job status")
    message: str
    estimated_duration_seconds: int = Field(..., description="Estimated training time")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class BoilerState(str, Enum):
    """Boiler operational state."""

    OFF = "off"
    IGNITION = "ignition"
    ON = "on"
    MODULATING = "modulating"
    ERROR = "error"


class BoilerResponse(BaseModel):
    """Current boiler state."""

    state: BoilerState = Field(..., description="Boiler state")
    power_kw: float = Field(..., description="Current power output (kW)")
    flow_temp_c: float = Field(..., description="Flow temperature setpoint (°C)")
    return_temp_c: float = Field(..., description="Return temperature (°C)")
    runtime_minutes: float = Field(..., description="Total runtime in current cycle (minutes)")
    last_state_change: str = Field(..., description="ISO-8601 last state change")
    modulation_percent: Optional[float] = Field(None, description="Modulation % (0-100)")
    error_code: Optional[str] = Field(None, description="Error code if state == ERROR")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class ControlDecision(BaseModel):
    """A single control decision."""

    id: str = Field(..., description="Decision ID (UUID)")
    timestamp: str = Field(..., description="Decision timestamp (ISO-8601)")
    decision_type: str = Field(..., description="Type: boiler_setpoint, flow_temp, mixer_position, pump_on_off")
    target_value: float = Field(..., description="Target value (temp in °C, position 0-100, etc)")
    device: str = Field(..., description="Target device (boiler, mixer, pump, etc)")
    reason: str = Field(..., description="Why decision was made")
    actual_value: Optional[float] = Field(None, description="Actual applied value")


class DecisionsResponse(BaseModel):
    """Last N control decisions."""

    decisions: list[ControlDecision] = Field(..., description="Last decisions (newest first)")
    count: int = Field(..., description="Number of decisions returned")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class OverrideFlowTempRequest(BaseModel):
    """Request to override flow temperature."""

    flow_temp_c: float = Field(..., ge=20, le=80, description="Target flow temperature (20-80°C)")
    duration_minutes: int = Field(default=30, ge=5, le=1440, description="Override duration (5min-24h)")
    reason: str = Field(..., description="Reason for manual override")


class OverrideResponse(BaseModel):
    """Response to override request."""

    override_id: str = Field(..., description="Override session ID")
    flow_temp_c: float = Field(..., description="Override temperature (°C)")
    duration_minutes: int = Field(..., description="Override duration (minutes)")
    expires_at: str = Field(..., description="ISO-8601 expiration time")
    message: str
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


# ============================================================================
# Helper Functions
# ============================================================================

def get_timestamp() -> str:
    """Get current timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


async def query_influxdb(
    query_api: "QueryApi",
    flux_query: str,
) -> list[dict]:
    """Execute InfluxDB Flux query and return results as dicts.
    
    Args:
        query_api: InfluxDB QueryApi instance
        flux_query: Flux query string
        
    Returns:
        List of result dicts
    """
    try:
        tables = query_api.query(flux_query)
        results = []
        for table in tables:
            for record in table.records:
                results.append({
                    "time": record.get_time(),
                    "measurement": record.get_measurement(),
                    "field": record.get_field(),
                    "value": record.get_value(),
                    "tags": record.tags,
                })
        return results
    except Exception as e:
        logger.error("InfluxDB query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"InfluxDB query failed: {str(e)}"
        )


async def query_postgres(
    db_pool: asyncpg.Pool,
    query: str,
    *args,
) -> list[dict]:
    """Execute PostgreSQL query and return results as dicts.
    
    Args:
        db_pool: AsyncPG connection pool
        query: SQL query string
        args: Query parameters
        
    Returns:
        List of result dicts
    """
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized"
        )
    try:
        async with db_pool.acquire() as conn:
            records = await conn.fetch(query, *args)
            return [dict(record) for record in records]
    except Exception as e:
        logger.error("PostgreSQL query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database query failed: {str(e)}"
        )


# ============================================================================
# Endpoint 1: GET /api/energy — Energy Consumption
# ============================================================================

@router.get(
    "/energy",
    response_model=EnergyResponse,
    summary="Get energy consumption by period",
    description="Fetch total energy consumed and breakdown by source (boiler, pump, PV, etc)"
)
async def get_energy(
    period: str = "day",
) -> EnergyResponse:
    """Get energy consumption with breakdown.
    
    Periods:
    - "hour": Last 60 minutes
    - "day": Last 24 hours
    - "month": Last 30 days
    
    Query InfluxDB for measurements:
    - energy.boiler (kWh)
    - energy.pump (kWh)
    - energy.supplemental (kWh)
    - energy.pv_exported (kWh)
    - energy.pv_used (kWh)
    """
    if period not in ["hour", "day", "month"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be 'hour', 'day', or 'month'"
        )

    # Calculate time window
    now = datetime.now(timezone.utc)
    if period == "hour":
        start = now - timedelta(hours=1)
        window = "60m"
    elif period == "day":
        start = now - timedelta(days=1)
        window = "24h"
    else:  # month
        start = now - timedelta(days=30)
        window = "30d"

    # For demo: return synthetic data
    # In production, query InfluxDB here
    breakdown = EnergyBreakdown(
        boiler=15.4,
        circulation_pump=2.8,
        supplemental_heat=0.0,
        pv_exported=8.2,
        pv_used=12.6,
    )

    return EnergyResponse(
        total_consumed_kwh=sum([
            breakdown.boiler,
            breakdown.circulation_pump,
            breakdown.supplemental_heat,
        ]),
        period=period,
        period_start=start.isoformat(),
        period_end=now.isoformat(),
        breakdown=breakdown,
        timestamp=get_timestamp(),
    )


# ============================================================================
# Endpoint 2: GET /api/analytics/{period} — Thermal Analytics
# ============================================================================

@router.get(
    "/analytics/{period}",
    response_model=AnalyticsResponse,
    summary="Get thermal system analytics",
    description="Fetch room temperature, setpoint, boiler runtime, PV utilization stats"
)
async def get_analytics(
    period: str,
) -> AnalyticsResponse:
    """Get thermal system analytics for a period.
    
    Periods:
    - "hour": Last 60 minutes
    - "day": Last 24 hours
    - "week": Last 7 days
    - "month": Last 30 days
    
    Aggregates from InfluxDB:
    - thermal.room_temp (°C)
    - thermal.setpoint (°C)
    - thermal.boiler_runtime (minutes)
    - thermal.mixing_valve_position (0-100)
    - energy.pv_utilization (%)
    """
    if period not in ["hour", "day", "week", "month"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be 'hour', 'day', 'week', or 'month'"
        )

    # Calculate time window
    now = datetime.now(timezone.utc)
    if period == "hour":
        start = now - timedelta(hours=1)
    elif period == "day":
        start = now - timedelta(days=1)
    elif period == "week":
        start = now - timedelta(days=7)
    else:  # month
        start = now - timedelta(days=30)

    # For demo: return synthetic data
    # In production, query InfluxDB here
    thermal_stats = ThermalStats(
        avg_room_temp_c=21.2,
        current_room_temp_c=21.5,
        avg_setpoint_c=21.0,
        boiler_runtime_minutes=45.0,
        boiler_on_duty_cycle=3.1,
        pv_utilization_percent=68.5,
        mixing_valve_avg_position=65.0,
    )

    return AnalyticsResponse(
        period=period,
        period_start=start.isoformat(),
        period_end=now.isoformat(),
        thermal_stats=thermal_stats,
        timestamp=get_timestamp(),
    )


# ============================================================================
# Endpoint 3: GET /api/model/status — NN Model Status
# ============================================================================

@router.get(
    "/model/status",
    response_model=ModelStatusResponse,
    summary="Get neural network model status",
    description="Check NN model readiness, training progress, and accuracy"
)
async def get_model_status() -> ModelStatusResponse:
    """Get NN model status from database.
    
    Queries hems.model_metadata table for:
    - status (idle, training, ready, error)
    - last_trained timestamp
    - training_loss
    - accuracy
    - retraining_progress (if training)
    """
    try:
        # For demo: return synthetic status
        # In production, query PostgreSQL: 
        # SELECT * FROM hems.model_metadata WHERE id = 'primary_model' LIMIT 1
        now = datetime.now(timezone.utc)
        last_trained = now - timedelta(hours=12)

        return ModelStatusResponse(
            status=ModelStatus.READY,
            model_id="hems-thermal-v2",
            last_trained=last_trained.isoformat(),
            training_loss=0.012,
            accuracy=0.945,
            retraining_progress=None,
            timestamp=get_timestamp(),
        )
    except Exception as e:
        logger.error("Failed to fetch model status: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch model status: {str(e)}"
        )


# ============================================================================
# Endpoint 4: POST /api/model/retrain — Trigger Async Retraining
# ============================================================================

@router.post(
    "/model/retrain",
    response_model=RetrainResponse,
    summary="Trigger neural network retraining",
    description="Queue async model retraining with recent data"
)
async def retrain_model(
    request: RetrainRequest,
    background_tasks: BackgroundTasks,
) -> RetrainResponse:
    """Trigger async NN model retraining.
    
    - Validates request parameters
    - Creates job record in PostgreSQL
    - Queues background task
    - Returns job_id for polling
    
    Job table: hems.training_jobs (id, status, started_at, completed_at, error)
    """
    try:
        # For demo: create a mock job ID
        from uuid import uuid4
        job_id = str(uuid4())
        
        # In production:
        # 1. Insert job record: INSERT INTO hems.training_jobs (id, status, epochs, batch_size, ...) VALUES (...)
        # 2. Queue background task: background_tasks.add_task(retrain_worker, job_id, ...)
        
        # Mock background task
        async def mock_retrain(job_id: str):
            logger.info("Mock retraining job %s started", job_id)
            await asyncio.sleep(2)  # Simulate work
            logger.info("Mock retraining job %s completed", job_id)

        background_tasks.add_task(mock_retrain, job_id)

        return RetrainResponse(
            job_id=job_id,
            status="queued",
            message=f"Retraining job {job_id} queued successfully",
            estimated_duration_seconds=180,
            timestamp=get_timestamp(),
        )
    except Exception as e:
        logger.error("Failed to queue retraining: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue retraining: {str(e)}"
        )


# ============================================================================
# Endpoint 5: GET /api/boiler — Current Boiler State
# ============================================================================

@router.get(
    "/boiler",
    response_model=BoilerResponse,
    summary="Get current boiler state",
    description="Fetch boiler status, power, flow/return temps, runtime"
)
async def get_boiler_state(
) -> BoilerResponse:
    """Get current boiler operational state.
    
    Queries InfluxDB for latest values:
    - boiler.state (off, ignition, on, modulating, error)
    - boiler.power_kw
    - boiler.flow_temp
    - boiler.return_temp
    - boiler.runtime_minutes
    - boiler.modulation_percent
    - boiler.error_code
    """
    try:
        # For demo: return synthetic boiler state
        # In production, query InfluxDB for latest boiler values
        now = datetime.now(timezone.utc)
        last_change = now - timedelta(minutes=12)

        return BoilerResponse(
            state=BoilerState.ON,
            power_kw=18.5,
            flow_temp_c=55.0,
            return_temp_c=48.2,
            runtime_minutes=12.0,
            last_state_change=last_change.isoformat(),
            modulation_percent=85.0,
            error_code=None,
            timestamp=get_timestamp(),
        )
    except Exception as e:
        logger.error("Failed to fetch boiler state: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch boiler state: {str(e)}"
        )


# ============================================================================
# Endpoint 6: GET /api/decisions/latest — Last Control Decisions
# ============================================================================

@router.get(
    "/decisions/latest",
    response_model=DecisionsResponse,
    summary="Get last control decisions",
    description="Fetch the last 5 control decisions made by HEMS"
)
async def get_latest_decisions(
    limit: int = 5,
) -> DecisionsResponse:
    """Get the last N control decisions.
    
    Queries hems.control_decisions table:
    - id, timestamp, decision_type, target_value, device, reason, actual_value
    
    Returns newest decisions first.
    """
    try:
        if limit < 1 or limit > 50:
            limit = 5

        # For demo: return synthetic decisions
        # In production, query PostgreSQL:
        # SELECT * FROM hems.control_decisions 
        # ORDER BY timestamp DESC LIMIT $1
        now = datetime.now(timezone.utc)

        decisions = [
            ControlDecision(
                id="dec-001",
                timestamp=(now - timedelta(minutes=2)).isoformat(),
                decision_type="boiler_setpoint",
                target_value=60.0,
                device="boiler",
                reason="Room temp below setpoint, increasing flow temp",
                actual_value=60.0,
            ),
            ControlDecision(
                id="dec-002",
                timestamp=(now - timedelta(minutes=8)).isoformat(),
                decision_type="mixer_position",
                target_value=72.0,
                device="mixer",
                reason="Adjusting mixing valve for better response",
                actual_value=71.5,
            ),
        ]

        return DecisionsResponse(
            decisions=decisions,
            count=len(decisions),
            timestamp=get_timestamp(),
        )
    except Exception as e:
        logger.error("Failed to fetch control decisions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch control decisions: {str(e)}"
        )


# ============================================================================
# Endpoint 7: POST /api/override/flow_temp — Manual Flow Temp Override
# ============================================================================

@router.post(
    "/override/flow_temp",
    response_model=OverrideResponse,
    summary="Set manual flow temperature override",
    description="Temporarily override boiler flow temp setpoint"
)
async def override_flow_temp(
    request: OverrideFlowTempRequest,
) -> OverrideResponse:
    """Set manual flow temperature override.
    
    - Validates temperature (20-80°C) and duration (5min-24h)
    - Creates override record in PostgreSQL
    - Signals boiler controller to apply override
    - Returns override_id for tracking
    
    Override table: hems.flow_temp_overrides (id, flow_temp, duration, reason, created_at, expires_at)
    """
    try:
        from uuid import uuid4
        override_id = str(uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=request.duration_minutes)

        # In production:
        # 1. INSERT INTO hems.flow_temp_overrides (id, flow_temp_c, duration_minutes, reason, expires_at) VALUES (...)
        # 2. Signal boiler controller via Redis or direct call

        return OverrideResponse(
            override_id=override_id,
            flow_temp_c=request.flow_temp_c,
            duration_minutes=request.duration_minutes,
            expires_at=expires_at.isoformat(),
            message=f"Flow temp override {override_id} active until {expires_at.isoformat()}",
            timestamp=get_timestamp(),
        )
    except Exception as e:
        logger.error("Failed to create flow temp override: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create override: {str(e)}"
        )
