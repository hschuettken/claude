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
import time
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
from circulation_pump import CirculationPumpScheduler, PumpState
from config import HEMSSettings
from database import HEMSDatabase
from mixer_controller import MixerController
from routes import router
from api import router as api_router

HEALTHCHECK_FILE = Path(os.environ.get("HEMS_DATA_DIR", "/app/data")) / "healthcheck"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hems")


# Global state
_control_loop_task: Optional[asyncio.Task] = None
_thermal_collector_task: Optional[asyncio.Task] = None  # Phase 3: Thermal data collector
_mixer_controller: Optional[MixerController] = None
_boiler_manager: Optional[BoilerManager] = None
_circulation_pump: Optional[CirculationPumpScheduler] = None
_influxdb_client: Optional[influxdb_client.InfluxDBClient] = None
_influxdb_write_api = None
_hems_db: Optional[HEMSDatabase] = None

# Sensor state tracking for graceful degradation
_sensor_cache: dict[str, float] = {}  # Last known values
_sensor_availability: dict[str, bool] = {}  # Current availability status
_sensor_last_update: dict[str, float] = {}  # Timestamp of last successful fetch


# ---------------------------------------------------------------------------
# Pydantic models for control tick response
# ---------------------------------------------------------------------------


class ControlDecisionResponse(BaseModel):
    timestamp: str
    valve_position_pct: float
    boiler_should_fire: bool
    boiler_state: str
    circulation_pump_on: bool
    circulation_pump_state: str
    circulation_pump_runtime_hours: float
    setpoint_c: Optional[float] = None
    measured_flow_temp_c: Optional[float] = None
    demand_w: Optional[float] = None
    error_message: Optional[str] = None
    degraded: bool = False  # True if operating with fallback values
    is_available: dict[str, bool] = {}  # Per-sensor availability


class SensorHealth(BaseModel):
    entity_id: str
    room_id: Optional[str] = None
    available: bool
    last_value: Optional[float] = None
    last_update_unix: Optional[float] = None
    error_message: Optional[str] = None


class HEMSHealthResponse(BaseModel):
    status: str  # "healthy", "degraded", "critical"
    timestamp: str
    sensors: dict[str, SensorHealth]
    degraded_rooms: list[str] = []  # Rooms with missing/unavailable sensors
    control_loop_active: bool
    database_available: bool


# ---------------------------------------------------------------------------
# Sensor state management
# ---------------------------------------------------------------------------


def _update_sensor_state(entity_id: str, value: Optional[float], available: bool = True) -> None:
    """Update sensor cache and availability state.
    
    Args:
        entity_id: HA entity ID (e.g., 'sensor.heating_flow_temperature')
        value: Measured value, or None if unavailable
        available: Whether sensor is online
    """
    _sensor_availability[entity_id] = available
    
    if available and value is not None:
        _sensor_cache[entity_id] = value
        _sensor_last_update[entity_id] = time.time()
        logger.debug(f"Sensor {entity_id} updated: {value}")
    else:
        logger.warning(f"Sensor {entity_id} unavailable or returned None")


def _get_sensor_value(entity_id: str, default: float = 0.0) -> tuple[float, bool]:
    """Get sensor value with fallback to last known value.
    
    Returns:
        (value, is_available) - value is last known or default if never seen
    """
    available = _sensor_availability.get(entity_id, False)
    value = _sensor_cache.get(entity_id, default)
    return value, available


def _get_all_sensor_health() -> dict[str, SensorHealth]:
    """Get health status for all known sensors."""
    health = {}
    for entity_id in list(_sensor_availability.keys()) + list(_sensor_cache.keys()):
        health[entity_id] = SensorHealth(
            entity_id=entity_id,
            available=_sensor_availability.get(entity_id, False),
            last_value=_sensor_cache.get(entity_id),
            last_update_unix=_sensor_last_update.get(entity_id),
        )
    return health


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


def _write_circulation_pump_to_influx(
    write_api: Optional[object],
    settings: HEMSSettings,
    pump_should_run: bool,
    pump_state: str,
    runtime_hours: float,
) -> None:
    """Write circulation pump state to InfluxDB."""
    if not write_api:
        return

    try:
        point = (
            influxdb_client.Point("hems_circulation_pump")
            .tag("service", "hems")
            .field("pump_on", pump_should_run)
            .field("pump_state", pump_state)
            .field("runtime_hours", runtime_hours)
        )

        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
        logger.debug("Wrote circulation pump state to InfluxDB")
    except Exception as e:
        logger.warning("Failed to write circulation pump state to InfluxDB: %s", e)


async def _publish_pump_schedule_to_ha(
    in_scheduled_window: bool,
    time_windows: Optional[list] = None,
) -> bool:
    """Publish circulation pump schedule state to Home Assistant.
    
    Updates switch.circulation_pump_schedule_active entity via orchestrator.
    Also logs time windows for debugging.
    
    Args:
        in_scheduled_window: Whether currently in a scheduled pump window
        time_windows: Optional list of TimeWindow objects for logging
        
    Returns:
        True if published successfully, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Call orchestrator to set HA switch state
            response = await client.post(
                "http://orchestrator:8100/tools/execute",
                json={
                    "tool": "ha_set_state",
                    "params": {
                        "entity_id": "switch.circulation_pump_schedule_active",
                        "state": "on" if in_scheduled_window else "off",
                        "attributes": {
                            "friendly_name": "Circulation Pump Schedule Active",
                            "icon": "mdi:pump",
                        },
                    },
                },
            )
            if response.status_code == 200:
                logger.debug(
                    "Published circulation pump schedule state to HA: %s",
                    "active" if in_scheduled_window else "inactive",
                )
                return True
            else:
                logger.warning("Orchestrator returned status %d when setting pump schedule", response.status_code)
                return False
    except asyncio.TimeoutError:
        logger.warning("Timeout publishing circulation pump schedule to HA")
        return False
    except Exception as e:
        logger.warning("Failed to publish circulation pump schedule to HA: %s", e)
        return False


# ---------------------------------------------------------------------------
# Control logic
# ---------------------------------------------------------------------------


async def _fetch_flow_temperature() -> tuple[Optional[float], bool]:
    """Fetch current flow temperature from Home Assistant via orchestrator.

    Returns:
        (temperature, is_available) - temperature in °C, or None if unavailable.
    """
    entity_id = "sensor.heating_flow_temperature"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Call orchestrator /tools/execute to fetch HA entity
            response = await client.post(
                "http://orchestrator:8100/tools/execute",
                json={
                    "tool": "ha_get_state",
                    "params": {
                        "entity_id": entity_id,
                    },
                },
            )
            if response.status_code == 200:
                data = response.json()
                state = data.get("state")
                
                # Handle None, "unavailable", "unknown", or non-numeric values
                if state is None or state == "unavailable" or state == "unknown":
                    _update_sensor_state(entity_id, None, available=False)
                    logger.warning(f"HA entity {entity_id} returned: {state}")
                    # Return cached value if available
                    cached, _ = _get_sensor_value(entity_id, default=50.0)
                    return cached, False
                
                try:
                    temp = float(state)
                    _update_sensor_state(entity_id, temp, available=True)
                    logger.debug("Fetched flow temp from HA: %.1f°C", temp)
                    return temp, True
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to convert HA state to float: {state} ({e})")
                    _update_sensor_state(entity_id, None, available=False)
                    cached, _ = _get_sensor_value(entity_id, default=50.0)
                    return cached, False
            else:
                logger.warning("Orchestrator returned status %d", response.status_code)
                _update_sensor_state(entity_id, None, available=False)
                # Return cached value
                cached, _ = _get_sensor_value(entity_id, default=50.0)
                return cached, False
    except asyncio.TimeoutError:
        logger.warning("Timeout fetching flow temperature from orchestrator")
        _update_sensor_state(entity_id, None, available=False)
        cached, _ = _get_sensor_value(entity_id, default=50.0)
        return cached, False
    except Exception as e:
        logger.warning("Failed to fetch flow temperature: %s", e)
        _update_sensor_state(entity_id, None, available=False)
        # Return cached value with sensible default
        cached, _ = _get_sensor_value(entity_id, default=50.0)
        return cached, False


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

    Reads schedule/demand, fetches flow temp from HA, calls MixerController,
    BoilerManager, and CirculationPumpScheduler, writes decisions to InfluxDB.
    
    Gracefully handles unavailable sensors by using cached/default values.
    """
    global _mixer_controller, _boiler_manager, _circulation_pump, _influxdb_write_api

    if not _mixer_controller or not _boiler_manager or not _circulation_pump:
        logger.error("Control loop: mixer_controller, boiler_manager, or circulation_pump not initialized")
        return

    logger.info("Control loop started (interval=10s)")

    while True:
        degraded = False
        try:
            # Fetch current state with graceful fallback
            measured_temp, temp_available = await _fetch_flow_temperature()
            demand_w = await _fetch_heating_demand()

            # Default setpoint: 50°C
            setpoint = 50.0

            # Track degradation
            if not temp_available:
                degraded = True
                logger.warning("Using fallback flow temperature (sensor unavailable)")

            # Call mixer controller with guaranteed float value
            if measured_temp is not None:
                valve_pos = _mixer_controller.compute(
                    setpoint_c=setpoint,
                    measured_c=float(measured_temp),
                    dt_s=10.0,
                )
            else:
                valve_pos = _mixer_controller.last_output
                logger.warning("No measured temp available; using last valve position")

            # Call boiler manager
            if demand_w is None:
                demand_w = 0.0
            boiler_should_fire = _boiler_manager.should_fire(demand_w=demand_w)
            boiler_state = _boiler_manager.get_state().value

            # Call circulation pump scheduler
            # For Phase 1, we use simple heuristic: any room with active schedule needs circulation
            # TODO: Fetch actual room temperatures from HA climate entities
            room_targets = {}
            room_actuals = {}
            try:
                # Attempt to get primary room schedule
                if _hems_db:
                    now = datetime.now(timezone.utc)
                    dow = now.weekday()
                    current_time = now.time()
                    schedule = await _hems_db.get_current_schedule("living_room", dow, current_time)
                    if schedule:
                        room_targets["living_room"] = schedule.target_temp
                        # Use cached room temperature if available
                        room_actuals["living_room"] = _sensor_cache.get("sensor.room_temperature", 20.0)
            except Exception as e:
                logger.warning("Could not fetch room schedule for circulation pump: %s", e)
            
            # Determine if pump should run
            pump_should_run = _circulation_pump.should_pump(
                boiler_active=boiler_should_fire,
                room_targets=room_targets,
                room_actuals=room_actuals,
            )
            pump_state = _circulation_pump.get_state().value
            pump_runtime_hours = _circulation_pump.get_runtime_hours()

            # Publish pump schedule state to Home Assistant
            await _publish_pump_schedule_to_ha(
                in_scheduled_window=_circulation_pump.in_scheduled_window,
                time_windows=_circulation_pump.get_time_windows(),
            )

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
                _write_circulation_pump_to_influx(
                    _influxdb_write_api,
                    settings,
                    pump_should_run=pump_should_run,
                    pump_state=pump_state,
                    runtime_hours=pump_runtime_hours,
                )

            log_level = logging.WARNING if degraded else logging.INFO
            logger.log(
                log_level,
                "Control tick: valve=%.1f%%, boiler=%s (fire=%s), pump=%s, temp=%.1f°C, demand=%.0fW%s",
                valve_pos,
                boiler_state,
                boiler_should_fire,
                pump_state,
                measured_temp if measured_temp is not None else -1,
                demand_w if demand_w is not None else -1,
                " [DEGRADED]" if degraded else "",
            )

        except Exception as e:
            logger.error("Error in control loop: %s", e, exc_info=True)

        # Sleep 10 seconds before next tick
        await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# Phase 3: Thermal Training Data Collector
# ---------------------------------------------------------------------------


async def thermal_data_collector(settings: HEMSSettings) -> None:
    """Background task: collect thermal training data every 15 minutes.

    Captures current thermal state (flow temp, room temp, setpoint, etc.)
    and logs to InfluxDB thermal_training measurement for ML model training.

    Runs every 15 minutes (900 seconds).
    """
    global _influxdb_write_api, _sensor_cache

    logger.info("Thermal data collector started (interval=900s / 15 min)")

    while True:
        try:
            # Fetch current thermal state
            measured_temp, temp_available = await _fetch_flow_temperature()
            demand_w = await _fetch_heating_demand()

            # Default setpoint from control loop
            setpoint = 50.0

            # Get room temperature from cache (updated by control loop)
            room_temp = _sensor_cache.get("sensor.room_temperature", 20.0)
            outside_temp = _sensor_cache.get("sensor.outside_temperature")

            # Determine if heating is currently active (placeholder)
            # In production, this would check boiler state
            actual_heating = demand_w is not None and demand_w > 0

            # Log to InfluxDB
            if _influxdb_write_api:
                try:
                    point = (
                        influxdb_client.Point("thermal_training")
                        .tag("room_id", "primary")  # TODO: Iterate over multiple rooms
                        .field("flow_temp", float(measured_temp or 50.0))
                        .field("room_temp", float(room_temp))
                        .field("setpoint", float(setpoint))
                        .field("actual_heating", actual_heating)
                    )

                    if outside_temp is not None:
                        point = point.field("outside_temp", float(outside_temp))

                    _influxdb_write_api.write(
                        bucket=settings.influxdb_bucket,
                        org=settings.influxdb_org,
                        record=point
                    )

                    logger.debug(
                        "Thermal snapshot logged: flow=%.1f°C, room=%.1f°C, sp=%.1f°C, heating=%s",
                        measured_temp or 50.0,
                        room_temp,
                        setpoint,
                        actual_heating,
                    )
                except Exception as e:
                    logger.warning("Failed to log thermal snapshot: %s", e)

        except Exception as e:
            logger.error("Error in thermal data collector: %s", e, exc_info=True)

        # Sleep 15 minutes before next collection
        await asyncio.sleep(900)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _control_loop_task, _thermal_collector_task, _mixer_controller, _boiler_manager, _circulation_pump, _influxdb_client, _influxdb_write_api, _hems_db

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
        logger.warning("Could not initialize HEMS database (will retry on use): %s", e)
        # Set empty db for now — routes will handle gracefully
        app.state.db = None

    # Initialize controllers
    _mixer_controller = MixerController(kp=3.0, ki=0.15, max_integral=20, rate_limit=2.0)
    _boiler_manager = BoilerManager(min_off_time_s=600, min_on_time_s=300)
    _circulation_pump = CirculationPumpScheduler(min_runtime_s=600, max_runtime_s=3600, temp_hysteresis_c=0.5)
    logger.info("Controllers initialized: mixer_controller, boiler_manager, circulation_pump")

    # Initialize InfluxDB
    _influxdb_client, _influxdb_write_api = _init_influxdb(settings)
    app.state.influxdb_write_api = _influxdb_write_api
    app.state.influxdb_client = _influxdb_client  # For query operations (Phase 3)

    # Start background control loop
    _control_loop_task = asyncio.create_task(control_loop(settings))
    logger.info("Control loop task started")

    # Start thermal data collector (Phase 3)
    _thermal_collector_task = asyncio.create_task(thermal_data_collector(settings))
    logger.info("Thermal data collector task started")

    yield

    logger.info("HEMS shutting down")

    # Cancel control loop
    if _control_loop_task:
        _control_loop_task.cancel()
        try:
            await _control_loop_task
        except asyncio.CancelledError:
            pass

    # Cancel thermal collector
    if _thermal_collector_task:
        _thermal_collector_task.cancel()
        try:
            await _thermal_collector_task
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
    app.include_router(api_router)  # Phase 2 internal API endpoints

    # Add control tick endpoint
    @app.post("/api/v1/hems/control/tick", response_model=ControlDecisionResponse, tags=["hems"])
    async def control_tick() -> ControlDecisionResponse:
        """Execute a single control iteration (test endpoint).
        
        Returns 200 with degraded=true if sensors are unavailable (not 503).
        """
        global _mixer_controller, _boiler_manager, _circulation_pump

        if not _mixer_controller or not _boiler_manager or not _circulation_pump:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Controllers not yet initialized",
            )

        degraded = False
        try:
            # Fetch current state with graceful fallback
            measured_temp, temp_available = await _fetch_flow_temperature()
            demand_w = await _fetch_heating_demand()

            # Track degradation
            if not temp_available:
                degraded = True

            # Default setpoint
            setpoint = 50.0

            # Compute valve position with guaranteed value
            if measured_temp is not None:
                valve_pos = _mixer_controller.compute(
                    setpoint_c=setpoint,
                    measured_c=float(measured_temp),
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

            # Compute circulation pump decision
            room_targets = {}
            room_actuals = {}
            try:
                if _hems_db:
                    now = datetime.now(timezone.utc)
                    dow = now.weekday()
                    current_time = now.time()
                    schedule = await _hems_db.get_current_schedule("living_room", dow, current_time)
                    if schedule:
                        room_targets["living_room"] = schedule.target_temp
                        room_actuals["living_room"] = _sensor_cache.get("sensor.room_temperature", 20.0)
            except Exception as e:
                logger.debug("Could not fetch room schedule for pump in control_tick: %s", e)
            
            pump_should_run = _circulation_pump.should_pump(
                boiler_active=boiler_should_fire,
                room_targets=room_targets,
                room_actuals=room_actuals,
            )
            pump_state = _circulation_pump.get_state().value
            pump_runtime_hours = _circulation_pump.get_runtime_hours()

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
                _write_circulation_pump_to_influx(
                    _influxdb_write_api,
                    settings,
                    pump_should_run=pump_should_run,
                    pump_state=pump_state,
                    runtime_hours=pump_runtime_hours,
                )

            return ControlDecisionResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                valve_position_pct=valve_pos,
                boiler_should_fire=boiler_should_fire,
                boiler_state=boiler_state,
                circulation_pump_on=pump_should_run,
                circulation_pump_state=pump_state,
                circulation_pump_runtime_hours=pump_runtime_hours,
                setpoint_c=setpoint,
                measured_flow_temp_c=measured_temp,
                demand_w=demand_w,
                degraded=degraded,
                is_available={
                    "flow_temperature": temp_available,
                    "demand": demand_w is not None and demand_w > 0,
                    "pump": pump_state is not None,
                },
            )

        except Exception as e:
            logger.error("Error in control tick: %s", e, exc_info=True)
            return ControlDecisionResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                valve_position_pct=0.0,
                boiler_should_fire=False,
                boiler_state="error",
                circulation_pump_on=False,
                circulation_pump_state="error",
                circulation_pump_runtime_hours=0.0,
                error_message=str(e),
                degraded=True,
                is_available={},
            )
    
    # Add health check endpoint
    @app.get("/api/v1/hems/health", response_model=HEMSHealthResponse, tags=["hems"])
    async def hems_health() -> HEMSHealthResponse:
        """Get HEMS service health including sensor availability.
        
        Returns detailed per-sensor status and identifies degraded rooms.
        """
        sensor_health = _get_all_sensor_health()
        
        # Determine overall status
        num_sensors = len(sensor_health)
        available_count = sum(1 for s in sensor_health.values() if s.available)
        
        if num_sensors == 0:
            status = "healthy"  # No sensors known yet
        elif available_count == num_sensors:
            status = "healthy"
        elif available_count > 0:
            status = "degraded"
        else:
            status = "critical"
        
        # List degraded rooms (missing flow temp, etc.)
        degraded_rooms = []
        if not _sensor_availability.get("sensor.heating_flow_temperature", False):
            degraded_rooms.append("heating_system")
        
        return HEMSHealthResponse(
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensors=sensor_health,
            degraded_rooms=degraded_rooms,
            control_loop_active=_control_loop_task is not None and not _control_loop_task.done(),
            database_available=_hems_db is not None,
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
