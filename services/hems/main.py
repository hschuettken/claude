"""HEMS — Home Energy Management System service.

Exposes REST API for energy schedule management, mode control,
and status reporting. Coordinates with Home Assistant and the
central Orchestrator.

Endpoints:
  GET  /health
  GET  /api/v1/hems/status
  GET  /api/v1/hems/schedule
  POST /api/v1/hems/schedule
  GET  /api/v1/hems/mode
  POST /api/v1/hems/mode
  POST /api/v1/hems/control/tick — single control iteration (test endpoint)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import influxdb_client
from fastapi import FastAPI, HTTPException, status
from influxdb_client.client.write_api import SYNCHRONOUS
from pydantic import BaseModel

from boiler_manager import BoilerManager, BoilerState
from config import HEMSSettings
from database import HEMSDatabase
from mixer_controller import MixerController
from routes import router

HEALTHCHECK_FILE = Path(os.environ.get("HEMS_DATA_DIR", "/app/data")) / "healthcheck"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hems")


# Global state
_control_loop_task: Optional[asyncio.Task] = None
_mixer_controller: Optional[MixerController] = None
_boiler_manager: Optional[BoilerManager] = None
_influxdb_client: Optional[influxdb_client.InfluxDBClient] = None
_influxdb_write_api = None
_hems_db: Optional[HEMSDatabase] = None


# ---------------------------------------------------------------------------
# Pydantic models for control tick response
# ---------------------------------------------------------------------------


class ControlDecisionResponse(BaseModel):
    timestamp: str
    valve_position_pct: float
    boiler_should_fire: bool
    boiler_state: str
    setpoint_c: Optional[float] = None
    measured_flow_temp_c: Optional[float] = None
    demand_w: Optional[float] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# InfluxDB helpers
# ---------------------------------------------------------------------------


def _init_influxdb(settings: HEMSSettings) -> tuple[Optional[influxdb_client.InfluxDBClient], Optional[object]]:
    """Initialize InfluxDB client and write API."""
    if not settings.influxdb_token:
        logger.warning("InfluxDB token not set — telemetry disabled")
        return None, None

    try:
        client = influxdb_client.InfluxDBClient(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org,
        )
        write_api = client.write_api(write_type=SYNCHRONOUS)
        logger.info("InfluxDB initialized: %s", settings.influxdb_url)
        return client, write_api
    except Exception as e:
        logger.error("Failed to initialize InfluxDB: %s", e)
        return None, None


def _write_hems_decision_to_influx(
    write_api: Optional[object],
    settings: HEMSSettings,
    valve_position: float,
    boiler_state: str,
    boiler_should_fire: bool,
    setpoint: Optional[float] = None,
    measured: Optional[float] = None,
    demand: Optional[float] = None,
) -> None:
    """Write control decision to InfluxDB."""
    if not write_api:
        return

    try:
        point = (
            influxdb_client.Point("hems_decisions")
            .tag("service", "hems")
            .field("valve_position_pct", valve_position)
            .field("boiler_should_fire", boiler_should_fire)
            .field("boiler_state", boiler_state)
        )

        if setpoint is not None:
            point = point.field("setpoint_c", setpoint)
        if measured is not None:
            point = point.field("measured_flow_temp_c", measured)
        if demand is not None:
            point = point.field("demand_w", demand)

        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
        logger.debug("Wrote hems_decisions to InfluxDB")
    except Exception as e:
        logger.warning("Failed to write hems_decisions to InfluxDB: %s", e)


# ---------------------------------------------------------------------------
# Control logic
# ---------------------------------------------------------------------------


async def _fetch_flow_temperature() -> Optional[float]:
    """Fetch current flow temperature from Home Assistant via orchestrator.

    Returns:
        Flow temperature in °C, or None if unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Call orchestrator /tools/execute to fetch HA entity
            response = await client.post(
                "http://orchestrator:8100/tools/execute",
                json={
                    "tool": "ha_get_state",
                    "params": {
                        "entity_id": "sensor.heating_flow_temperature",
                    },
                },
            )
            if response.status_code == 200:
                data = response.json()
                temp = float(data.get("state", 0))
                logger.debug("Fetched flow temp from HA: %.1f°C", temp)
                return temp
            else:
                logger.warning("Orchestrator returned status %d", response.status_code)
                return None
    except Exception as e:
        logger.warning("Failed to fetch flow temperature: %s", e)
        return None


async def _fetch_heating_demand() -> Optional[float]:
    """Fetch current heating demand in watts.

    Reads from DB schedule table to determine if we need heating now.

    Returns:
        Demand in watts, or None if unavailable.
    """
    global _hems_db
    
    if not _hems_db:
        return 0.0
    
    # For Phase 1, we fetch the current schedule target for a primary room
    # and derive demand from it. In Phase 2, we'll use a more sophisticated model.
    try:
        now = datetime.now(timezone.utc)
        dow = now.weekday()
        current_time = now.time()
        
        # Check primary room (living_room)
        schedule = await _hems_db.get_current_schedule("living_room", dow, current_time)
        if schedule:
            # Simple heuristic: if we have a schedule, demand = target temp
            # (will be refined in Phase 2)
            return float(schedule.target_temp)
    except Exception as e:
        logger.warning("Error fetching demand from schedule: %s", e)
    
    return 0.0


async def control_loop(settings: HEMSSettings) -> None:
    """Background control loop — runs every 10 seconds.

    Reads schedule/demand, fetches flow temp from HA, calls MixerController
    and BoilerManager, writes decisions to InfluxDB.
    """
    global _mixer_controller, _boiler_manager, _influxdb_write_api

    if not _mixer_controller or not _boiler_manager:
        logger.error("Control loop: mixer_controller or boiler_manager not initialized")
        return

    logger.info("Control loop started (interval=10s)")

    while True:
        try:
            # Fetch current state
            measured_temp = await _fetch_flow_temperature()
            demand_w = await _fetch_heating_demand()

            # Default setpoint: 50°C
            setpoint = 50.0

            # Call mixer controller
            if measured_temp is not None:
                valve_pos = _mixer_controller.compute(
                    setpoint_c=setpoint,
                    measured_c=measured_temp,
                    dt_s=10.0,
                )
            else:
                valve_pos = _mixer_controller.last_output
                logger.warning("Flow temp unavailable; using last valve position")

            # Call boiler manager
            if demand_w is None:
                demand_w = 0.0
            boiler_should_fire = _boiler_manager.should_fire(demand_w=demand_w)
            boiler_state = _boiler_manager.get_state().value

            # Write to InfluxDB
            if _influxdb_write_api:
                _write_hems_decision_to_influx(
                    _influxdb_write_api,
                    settings,
                    valve_position=valve_pos,
                    boiler_state=boiler_state,
                    boiler_should_fire=boiler_should_fire,
                    setpoint=setpoint,
                    measured=measured_temp,
                    demand=demand_w,
                )

            logger.info(
                "Control tick: valve=%.1f%%, boiler=%s (fire=%s), temp=%.1f°C, demand=%.0fW",
                valve_pos,
                boiler_state,
                boiler_should_fire,
                measured_temp or -1,
                demand_w or -1,
            )

        except Exception as e:
            logger.error("Error in control loop: %s", e, exc_info=True)

        # Sleep 10 seconds before next tick
        await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _control_loop_task, _mixer_controller, _boiler_manager, _influxdb_client, _influxdb_write_api, _hems_db

    settings: HEMSSettings = app.state.settings
    logger.info("HEMS starting up — mode=%s", settings.hems_mode)

    HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTHCHECK_FILE.touch()

    # Initialize database
    _hems_db = HEMSDatabase(settings.hems_db_url)
    try:
        await _hems_db.init()
        app.state.db = _hems_db
        logger.info("HEMS database initialized")
    except Exception as e:
        logger.error("Failed to initialize HEMS database: %s", e)
        # Continue without database (non-fatal for other services)

    # Initialize controllers
    _mixer_controller = MixerController(kp=0.8, ki=0.02, max_integral=20, rate_limit=2.0)
    _boiler_manager = BoilerManager(min_off_time_s=600, min_on_time_s=300)
    logger.info("Controllers initialized: mixer_controller, boiler_manager")

    # Initialize InfluxDB
    _influxdb_client, _influxdb_write_api = _init_influxdb(settings)
    app.state.influxdb_write_api = _influxdb_write_api

    # Start background control loop
    _control_loop_task = asyncio.create_task(control_loop(settings))
    logger.info("Control loop task started")

    yield

    logger.info("HEMS shutting down")

    # Cancel control loop
    if _control_loop_task:
        _control_loop_task.cancel()
        try:
            await _control_loop_task
        except asyncio.CancelledError:
            pass

    # Close InfluxDB client
    if _influxdb_client:
        _influxdb_client.close()

    # Close database
    if _hems_db:
        await _hems_db.close()

    HEALTHCHECK_FILE.unlink(missing_ok=True)


def create_app() -> FastAPI:
    settings = HEMSSettings()
    app = FastAPI(
        title="HEMS",
        description="Home Energy Management System",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(router)

    # Add control tick endpoint
    @app.post("/api/v1/hems/control/tick", response_model=ControlDecisionResponse, tags=["hems"])
    async def control_tick() -> ControlDecisionResponse:
        """Execute a single control iteration (test endpoint)."""
        global _mixer_controller, _boiler_manager

        if not _mixer_controller or not _boiler_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Controllers not yet initialized",
            )

        try:
            # Fetch current state
            measured_temp = await _fetch_flow_temperature()
            demand_w = await _fetch_heating_demand()

            # Default setpoint
            setpoint = 50.0

            # Compute valve position
            if measured_temp is not None:
                valve_pos = _mixer_controller.compute(
                    setpoint_c=setpoint,
                    measured_c=measured_temp,
                    dt_s=10.0,
                )
            else:
                valve_pos = _mixer_controller.last_output
                logger.warning("Flow temp unavailable in control tick")

            # Compute boiler decision
            if demand_w is None:
                demand_w = 0.0
            boiler_should_fire = _boiler_manager.should_fire(demand_w=demand_w)
            boiler_state = _boiler_manager.get_state().value

            # Write to InfluxDB
            if _influxdb_write_api:
                _write_hems_decision_to_influx(
                    _influxdb_write_api,
                    settings,
                    valve_position=valve_pos,
                    boiler_state=boiler_state,
                    boiler_should_fire=boiler_should_fire,
                    setpoint=setpoint,
                    measured=measured_temp,
                    demand=demand_w,
                )

            return ControlDecisionResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                valve_position_pct=valve_pos,
                boiler_should_fire=boiler_should_fire,
                boiler_state=boiler_state,
                setpoint_c=setpoint,
                measured_flow_temp_c=measured_temp,
                demand_w=demand_w,
            )

        except Exception as e:
            logger.error("Error in control tick: %s", e, exc_info=True)
            return ControlDecisionResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                valve_position_pct=0.0,
                boiler_should_fire=False,
                boiler_state="error",
                error_message=str(e),
            )

    return app


async def main() -> None:
    import uvicorn

    app = create_app()
    settings: HEMSSettings = app.state.settings
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
