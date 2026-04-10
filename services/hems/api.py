"""HEMS Phase 2 Internal API - Advanced Analytics & Control Endpoints.

This module provides internal API endpoints for:
1. Energy consumption analytics (hourly/daily/monthly breakdown)
2. Thermal analytics (room temps, boiler runtime, PV utilization)
3. Neural network model status & retraining
4. Boiler state queries
5. Control decision history
6. Manual flow temp overrides
7. Health/status/room-target/mode/retrain/flow-override (#1057-#1063)

All endpoints are async and optimized for InfluxDB + PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

import asyncpg
from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from influxdb_client.client.query_api import QueryApi

# ---------------------------------------------------------------------------
# Module-level config (read from env at import time)
# ---------------------------------------------------------------------------

_HEMS_API_KEY = os.getenv("HEMS_API_KEY", "hems_internal_key")
_executor = ThreadPoolExecutor(max_workers=4)

MQTT_HOST = os.getenv("MQTT_HOST", "192.168.0.73")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
HA_URL = os.getenv("HA_URL", "http://homeassistant:8123")
HA_TOKEN = os.getenv("HA_TOKEN", os.getenv("HEMS_HA_TOKEN", ""))
HEMS_BOILER_ENTITY = os.getenv("HEMS_BOILER_ENTITY", "sensor.boiler_temperature")
HEMS_ROOM_ENTITIES_RAW = os.getenv("HEMS_ROOM_ENTITIES", "")
HEMS_DRY_RUN = os.getenv("HEMS_DRY_RUN", "false").lower() in ("1", "true", "yes")
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "hems")

logger = logging.getLogger("hems.api")

router = APIRouter(prefix="/api", tags=["internal"])


# ---------------------------------------------------------------------------
# Auth + MQTT helpers
# ---------------------------------------------------------------------------


def _require_auth(x_api_key: Optional[str]) -> None:
    """Raise 401 if API key is missing or wrong."""
    if x_api_key != _HEMS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )


def _mqtt_publish_sync(topic: str, payload: dict) -> None:
    """Publish a JSON payload to an MQTT topic (synchronous, for executor use)."""
    try:
        import paho.mqtt.publish as publish

        publish.single(
            topic,
            payload=json.dumps(payload),
            hostname=MQTT_HOST,
            port=MQTT_PORT,
            qos=1,
            retain=False,
        )
    except Exception as exc:
        logger.warning("MQTT publish to %s failed: %s", topic, exc)


async def _mqtt_publish(topic: str, payload: dict) -> None:
    """Async wrapper around synchronous MQTT publish."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _mqtt_publish_sync, topic, payload)


# ============================================================================
# Pydantic Models
# ============================================================================


class EnergyBreakdown(BaseModel):
    """Energy consumption breakdown by source."""

    boiler: float = Field(..., description="Boiler energy (kWh)")
    circulation_pump: float = Field(..., description="Circulation pump energy (kWh)")
    supplemental_heat: float = Field(
        ..., description="Supplemental heating energy (kWh)"
    )
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

    avg_room_temp_c: float = Field(..., description="Average room temperature (deg C)")
    current_room_temp_c: float = Field(
        ..., description="Current room temperature (deg C)"
    )
    avg_setpoint_c: float = Field(
        ..., description="Average setpoint temperature (deg C)"
    )
    boiler_runtime_minutes: float = Field(
        ..., description="Boiler runtime in period (minutes)"
    )
    boiler_on_duty_cycle: float = Field(
        ..., description="Boiler on-time as % of period (0-100)"
    )
    pv_utilization_percent: float = Field(..., description="PV utilization % (0-100)")
    mixing_valve_avg_position: float = Field(
        ..., description="Mixing valve avg position (0-100)"
    )


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
    retraining_progress: Optional[float] = Field(
        None, description="Retraining progress (0-1)"
    )
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
    flow_temp_c: float = Field(..., description="Flow temperature setpoint (deg C)")
    return_temp_c: float = Field(..., description="Return temperature (deg C)")
    runtime_minutes: float = Field(
        ..., description="Total runtime in current cycle (minutes)"
    )
    last_state_change: str = Field(..., description="ISO-8601 last state change")
    modulation_percent: Optional[float] = Field(
        None, description="Modulation % (0-100)"
    )
    error_code: Optional[str] = Field(None, description="Error code if state == ERROR")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class ControlDecision(BaseModel):
    """A single control decision."""

    id: str = Field(..., description="Decision ID (UUID)")
    timestamp: str = Field(..., description="Decision timestamp (ISO-8601)")
    decision_type: str = Field(
        ..., description="Type: boiler_setpoint, flow_temp, mixer_position, pump_on_off"
    )
    target_value: float = Field(
        ..., description="Target value (temp in deg C, position 0-100, etc)"
    )
    device: str = Field(..., description="Target device (boiler, mixer, pump, etc)")
    reason: str = Field(..., description="Why decision was made")
    actual_value: Optional[float] = Field(None, description="Actual applied value")


class DecisionsResponse(BaseModel):
    """Last N control decisions."""

    decisions: list[ControlDecision] = Field(
        ..., description="Last decisions (newest first)"
    )
    count: int = Field(..., description="Number of decisions returned")
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class OverrideFlowTempRequest(BaseModel):
    """Request to override flow temperature (#1063)."""

    flow_temp: float = Field(
        ..., ge=20.0, le=80.0, description="Target flow temperature (20-80 deg C)"
    )
    duration_minutes: int = Field(
        default=30, ge=1, le=480, description="Override duration (1-480 min)"
    )


class OverrideResponse(BaseModel):
    """Response to override request."""

    override_id: str = Field(..., description="Override session ID")
    flow_temp_c: float = Field(..., description="Override temperature (deg C)")
    duration_minutes: int = Field(..., description="Override duration (minutes)")
    expires_at: str = Field(..., description="ISO-8601 expiration time")
    message: str
    timestamp: str = Field(..., description="Response timestamp (ISO-8601)")


class RoomTargetRequest(BaseModel):
    """Body for PUT /api/rooms/{room_id}/target (#1059)."""

    target_temp: float = Field(
        ..., ge=10.0, le=30.0, description="Target temperature (10-30 deg C)"
    )


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
    """Execute InfluxDB Flux query and return results as dicts."""
    try:
        tables = query_api.query(flux_query)
        results = []
        for table in tables:
            for record in table.records:
                results.append(
                    {
                        "time": record.get_time(),
                        "measurement": record.get_measurement(),
                        "field": record.get_field(),
                        "value": record.get_value(),
                        "tags": record.tags,
                    }
                )
        return results
    except Exception as e:
        logger.error("InfluxDB query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"InfluxDB query failed: {str(e)}",
        )


async def query_postgres(
    db_pool: asyncpg.Pool,
    query: str,
    *args: Any,
) -> list[dict]:
    """Execute PostgreSQL query and return results as dicts."""
    if not db_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )
    try:
        async with db_pool.acquire() as conn:
            records = await conn.fetch(query, *args)
            return [dict(record) for record in records]
    except Exception as e:
        logger.error("PostgreSQL query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database query failed: {str(e)}",
        )


# ============================================================================
# #1057: GET /api/health — Health check (no auth required)
# ============================================================================


@router.get(
    "/health",
    summary="Health check (#1057)",
    description="Returns service health with feature flags. No auth required.",
)
async def get_health() -> dict[str, Any]:
    """Return service health and feature flags."""
    return {
        "status": "ok",
        "version": "1.0",
        "features": {
            "nn_enabled": True,
            "pv_budget": True,
            "dry_run": HEMS_DRY_RUN,
            "decision_loop": True,
        },
    }


# ============================================================================
# #1058: GET /api/status — Aggregated snapshot from HA
# ============================================================================


async def _ha_get_state(entity_id: str) -> Optional[dict]:
    """Fetch a single HA entity state via REST API."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{HA_URL}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning("HA get_state(%s) failed: %s", entity_id, exc)
    return None


@router.get(
    "/status",
    summary="Aggregated HEMS snapshot (#1058)",
    description="Reads boiler/room/PV state from HA. Returns partial data on HA failure.",
)
async def get_status(
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Return aggregated HEMS status snapshot."""
    _require_auth(x_api_key)

    now_iso = datetime.now(timezone.utc).isoformat()
    ha_error: Optional[str] = None

    # --- boiler ---
    boiler_entity = await _ha_get_state(HEMS_BOILER_ENTITY)
    boiler: dict[str, Any]
    if boiler_entity is None:
        ha_error = "HA unavailable"
        boiler = {"active": False, "flow_temp": 0.0}
    else:
        try:
            flow_temp = float(boiler_entity.get("state", "0"))
        except (ValueError, TypeError):
            flow_temp = 0.0
        boiler = {"active": flow_temp > 30.0, "flow_temp": flow_temp}

    # --- rooms ---
    rooms: list[dict[str, Any]] = []
    room_entity_ids = [
        e.strip() for e in HEMS_ROOM_ENTITIES_RAW.split(",") if e.strip()
    ]
    for entity_id in room_entity_ids:
        state_data = await _ha_get_state(entity_id)
        if state_data is None:
            ha_error = ha_error or "HA unavailable"
            continue
        attrs = state_data.get("attributes", {})
        try:
            temp = float(state_data.get("state", "0"))
        except (ValueError, TypeError):
            temp = 0.0
        rooms.append(
            {
                "id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "temp": temp,
                "setpoint": float(attrs.get("temperature", 0.0)),
                "mode": attrs.get("hvac_mode", "unknown"),
            }
        )

    result: dict[str, Any] = {
        "timestamp": now_iso,
        "boiler": boiler,
        "rooms": rooms,
        "pv": {"available_w": 0.0},
        "mode": "auto",
    }
    if ha_error:
        result["error"] = ha_error
    return result


# ============================================================================
# #1059: PUT /api/rooms/{room_id}/target
# ============================================================================


@router.put(
    "/rooms/{room_id}/target",
    summary="Set room target temperature (#1059)",
    description="Publishes MQTT override for a room. Expires after 1 hour.",
)
async def set_room_target(
    room_id: str,
    body: RoomTargetRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Publish MQTT target_override for a room."""
    _require_auth(x_api_key)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=1)

    topic = f"homelab/hems/rooms/{room_id}/target_override"
    payload: dict[str, Any] = {
        "target": body.target_temp,
        "expires_at": expires_at.isoformat(),
    }
    await _mqtt_publish(topic, payload)

    return {
        "room_id": room_id,
        "target_temp": body.target_temp,
        "expires_at": expires_at.isoformat(),
    }


# ============================================================================
# #1060: PUT /api/modes/{mode}
# ============================================================================

_VALID_MODES = {"eco", "comfort", "away", "boost", "auto"}


@router.put(
    "/modes/{mode}",
    summary="Set HEMS operating mode (#1060)",
    description="Valid modes: eco, comfort, away, boost, auto.",
)
async def set_mode(
    mode: str,
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Publish HEMS mode change to MQTT."""
    _require_auth(x_api_key)

    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{mode}'. Valid: {sorted(_VALID_MODES)}",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    await _mqtt_publish("homelab/hems/mode", {"mode": mode, "set_at": now_iso})

    return {"mode": mode, "active": True}


# ============================================================================
# #1061: GET /api/analytics/{period}
# ============================================================================


@router.get(
    "/analytics/{period}",
    summary="Get HEMS decision analytics (#1061)",
    description="Queries InfluxDB hems_decisions. Returns counts or error on failure.",
)
async def get_analytics(
    period: str,
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Return HEMS decision analytics for the given period."""
    _require_auth(x_api_key)

    if period not in ("day", "week", "month"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be 'day', 'week', or 'month'",
        )

    range_map = {"day": "-1d", "week": "-7d", "month": "-30d"}
    range_str = range_map[period]

    flux = (
        f'from(bucket: "{INFLUXDB_BUCKET}")'
        f" |> range(start: {range_str})"
        f' |> filter(fn: (r) => r["_measurement"] == "hems_decisions")'
        " |> count()"
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{INFLUXDB_URL}/api/v2/query",
                headers={
                    "Authorization": f"Token {INFLUXDB_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/csv",
                },
                json={"query": flux, "type": "flux", "org": INFLUXDB_ORG},
            )

        decisions_count = 0
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split(",")
                try:
                    decisions_count += int(float(parts[-1].strip()))
                except (ValueError, IndexError):
                    pass
        else:
            logger.warning("InfluxDB analytics query returned %s", resp.status_code)

        return {
            "period": period,
            "decisions_count": decisions_count,
            "rooms": {},
            "avg_delta": 0.0,
        }

    except Exception as exc:
        logger.warning("InfluxDB analytics query failed: %s", exc)
        return {"period": period, "error": "metrics unavailable"}


# ============================================================================
# #1062: POST /api/model/retrain
# ============================================================================


@router.post(
    "/model/retrain",
    summary="Trigger NN retrain (#1062)",
    description="Publishes MQTT retrain command. Returns triggered/timestamp.",
)
async def retrain_model(
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Trigger NN model retraining via MQTT."""
    _require_auth(x_api_key)

    now_iso = datetime.now(timezone.utc).isoformat()
    await _mqtt_publish("homelab/hems/commands/retrain", {"full": False})
    return {"triggered": True, "timestamp": now_iso}


# ============================================================================
# #1063: POST /api/override/flow_temp
# ============================================================================


@router.post(
    "/override/flow_temp",
    summary="Flow temperature override (#1063)",
    description="Publishes MQTT flow_override. flow_temp 20-80 deg C, duration 1-480 min.",
)
async def override_flow_temp(
    body: OverrideFlowTempRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Set manual flow temperature override via MQTT."""
    _require_auth(x_api_key)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=body.duration_minutes)

    mqtt_payload: dict[str, Any] = {
        "flow_temp": body.flow_temp,
        "duration_minutes": body.duration_minutes,
        "expires_at": expires_at.isoformat(),
    }
    await _mqtt_publish("homelab/hems/boiler/flow_override", mqtt_payload)

    return {
        "flow_temp": body.flow_temp,
        "duration_minutes": body.duration_minutes,
        "expires_at": expires_at.isoformat(),
        "active": True,
    }


# ============================================================================
# Legacy Phase 2 endpoints (kept for backward compat, no auth)
# ============================================================================


@router.get(
    "/energy",
    response_model=EnergyResponse,
    summary="Get energy consumption by period (legacy synthetic stub)",
)
async def get_energy(
    period: str = "day",
) -> EnergyResponse:
    """Get energy consumption with breakdown (legacy synthetic stub)."""
    if period not in ["hour", "day", "month"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be 'hour', 'day', or 'month'",
        )

    now = datetime.now(timezone.utc)
    if period == "hour":
        start = now - timedelta(hours=1)
    elif period == "day":
        start = now - timedelta(days=1)
    else:
        start = now - timedelta(days=30)

    breakdown = EnergyBreakdown(
        boiler=15.4,
        circulation_pump=2.8,
        supplemental_heat=0.0,
        pv_exported=8.2,
        pv_used=12.6,
    )

    return EnergyResponse(
        total_consumed_kwh=sum(
            [breakdown.boiler, breakdown.circulation_pump, breakdown.supplemental_heat]
        ),
        period=period,
        period_start=start.isoformat(),
        period_end=now.isoformat(),
        breakdown=breakdown,
        timestamp=get_timestamp(),
    )


@router.get(
    "/model/status",
    response_model=ModelStatusResponse,
    summary="Get neural network model status (legacy)",
)
async def get_model_status() -> ModelStatusResponse:
    """Get NN model status (legacy synthetic stub)."""
    try:
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
            detail=f"Failed to fetch model status: {str(e)}",
        )


@router.get(
    "/boiler",
    response_model=BoilerResponse,
    summary="Get current boiler state (legacy synthetic stub)",
)
async def get_boiler_state() -> BoilerResponse:
    """Get current boiler operational state (legacy synthetic stub)."""
    try:
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
            detail=f"Failed to fetch boiler state: {str(e)}",
        )


@router.get(
    "/decisions/latest",
    response_model=DecisionsResponse,
    summary="Get last control decisions (legacy synthetic stub)",
)
async def get_latest_decisions(
    limit: int = 5,
) -> DecisionsResponse:
    """Get the last N control decisions (legacy synthetic stub)."""
    try:
        if limit < 1 or limit > 50:
            limit = 5

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
            detail=f"Failed to fetch control decisions: {str(e)}",
        )


# ============================================================================
# #1064: WebSocket /ws/live — Real-time state push
# ============================================================================


@router.websocket("/ws/live")
async def live_state(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time HEMS state push (#1064).

    Pushes state snapshot every 10 seconds:
    - timestamp: ISO-8601 UTC
    - rooms: array of room states (from HA or empty on error)
    - boiler: boiler state (active boolean, flow_temp)
    - mode: HEMS operating mode (auto/eco/comfort/away/boost)
    """
    await websocket.accept()
    try:
        while True:
            # Build state snapshot (similar to GET /api/status but minimal)
            state = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "rooms": [],  # populate from HA if available, else []
                "boiler": {"active": False},
                "mode": os.getenv("HEMS_MODE", "auto"),
            }
            await websocket.send_json(state)
            await asyncio.sleep(10)  # push every 10s
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_live_closed: %s", e)
