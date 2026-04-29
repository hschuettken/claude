"""Digital Twin — House + Energy + Life state model and simulation engine.

FastAPI service providing:
  - Real-time house state (rooms, energy, safe-mode)
  - Room registry (persistent, PostgreSQL-backed)
  - 4-scenario energy simulation (24h horizon)
  - NATS integration (state published, PV-forecast subscribed)

Port: 8238

NATS subjects published:
  digital.twin.state.updated     — latest HouseState snapshot
  digital.twin.simulation.done   — latest SimulationReport

NATS subjects subscribed:
  orchestrator.command.digital-twin   — refresh / simulate commands
  energy.pv.forecast_updated          — trigger re-simulation
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db, room_registry
from .config import settings
from .models import (
    EnergyState,
    HealthResponse,
    HouseState,
    RoomCreate,
    RoomResponse,
    RoomUpdate,
    ScenarioID,
    SimulationReport,
    SimulationRequest,
    SCENARIO_LABELS,
)
from .optimizer import build_recommendation, get_latest_recommendation, run_optimizer_loop
from .simulation import run_simulation
from .state_ingestion import HAStateIngester, PVForecastIngester

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# In-memory cache of the latest state + simulation report
_latest_house_state: Optional[HouseState] = None
_latest_simulation: Optional[SimulationReport] = None
_ingester: Optional[HAStateIngester] = None
_pv_ingester: Optional[PVForecastIngester] = None
_nats_client = None


# ─────────────────────────────────────────────────────────────────────────────
# NATS helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _nats_connect() -> None:
    global _nats_client
    try:
        import nats
        _nats_client = await nats.connect(settings.nats_url)
        logger.info("nats_connected url=%s", settings.nats_url)
        await _setup_subscriptions()
    except Exception as exc:
        logger.warning("nats_connect_failed url=%s error=%s", settings.nats_url, exc)
        _nats_client = None


async def _nats_publish(subject: str, data: dict) -> None:
    if _nats_client is None or _nats_client.is_closed:
        return
    try:
        payload = json.dumps(data, default=str).encode()
        await _nats_client.publish(subject, payload)
    except Exception as exc:
        logger.debug("nats_publish_failed subject=%s error=%s", subject, exc)


async def _setup_subscriptions() -> None:
    if _nats_client is None:
        return

    async def _on_command(msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            command = payload.get("command", "")
            logger.info("nats_command_received command=%s", command)
            if command == "refresh":
                asyncio.create_task(_refresh_state())
            elif command == "simulate":
                asyncio.create_task(_run_auto_simulation())
        except Exception as exc:
            logger.warning("nats_command_error error=%s", exc)

    async def _on_pv_forecast(msg) -> None:
        logger.info("pv_forecast_updated triggering resimulation")
        asyncio.create_task(_run_auto_simulation())

    await _nats_client.subscribe("orchestrator.command.digital-twin", cb=_on_command)
    await _nats_client.subscribe("energy.pv.forecast_updated", cb=_on_pv_forecast)
    logger.info("nats_subscriptions_ready")


async def _refresh_state() -> None:
    global _latest_house_state
    if _ingester is None:
        return
    try:
        _latest_house_state = await _ingester.fetch_house_state()
        logger.info("house_state_refreshed")
        await _nats_publish(
            "digital.twin.state.updated",
            _latest_house_state.model_dump(mode="json"),
        )
        # Persist snapshot to DB
        await db.execute(
            "INSERT INTO dt_state_snapshots (energy_state, room_states, safe_mode) "
            "VALUES ($1::jsonb, $2::jsonb, $3)",
            json.dumps(_latest_house_state.energy.model_dump(mode="json")),
            json.dumps(
                {k: v.model_dump(mode="json") for k, v in _latest_house_state.rooms.items()}
            ),
            _latest_house_state.safe_mode,
        )
    except Exception as exc:
        logger.error("state_refresh_failed error=%s", exc)


async def _run_auto_simulation() -> None:
    global _latest_simulation
    if _ingester is None or _pv_ingester is None:
        return
    try:
        energy = await _get_current_energy()
        pv_forecast = await _get_pv_forecast(energy.pv_total_power_w)
        request = SimulationRequest()
        _latest_simulation = run_simulation(
            request=request,
            energy_state=energy,
            pv_forecast_kwh=pv_forecast,
            **_sim_kwargs(),
        )
        logger.info(
            "simulation_done scenarios=%d best_cost=%s savings_eur=%s",
            len(_latest_simulation.scenarios),
            _latest_simulation.best_cost_id,
            _latest_simulation.savings_vs_baseline_eur,
        )
        await _nats_publish(
            "digital.twin.simulation.done",
            _latest_simulation.model_dump(mode="json"),
        )
        # Persist result to DB
        await db.execute(
            "INSERT INTO dt_simulation_results (horizon_hours, report) VALUES ($1, $2::jsonb)",
            _latest_simulation.horizon_hours,
            json.dumps(_latest_simulation.model_dump(mode="json"), default=str),
        )
    except Exception as exc:
        logger.error("auto_simulation_failed error=%s", exc)


async def _periodic_refresh() -> None:
    """Refresh house state every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        await _refresh_state()


def _sim_kwargs() -> dict:
    return dict(
        battery_cap_kwh=settings.battery_capacity_kwh,
        battery_max_kw=settings.battery_max_power_kw,
        ev_cap_kwh=settings.ev_capacity_kwh,
        ev_min_power_kw=settings.ev_min_charge_power_kw,
        ev_max_power_kw=settings.ev_max_charge_power_kw,
        tariff_import_ct=settings.tariff_import_ct,
        tariff_export_ct=settings.tariff_export_ct,
        preheat_power_kw=settings.preheat_power_kw,
        preheat_hours=settings.preheat_hours,
    )


async def _get_current_energy() -> EnergyState:
    if _latest_house_state:
        return _latest_house_state.energy
    if _ingester:
        return await _ingester.fetch_energy_state()
    return EnergyState()


async def _get_pv_forecast(current_pv_w: float) -> list[float]:
    if _pv_ingester:
        return await _pv_ingester.fetch_24h_kwh(current_pv_w=current_pv_w)
    from .state_ingestion import _shape_forecast
    return _shape_forecast(5.0)


# ─────────────────────────────────────────────────────────────────────────────
# Oracle registration
# ─────────────────────────────────────────────────────────────────────────────

async def _register_with_oracle() -> None:
    manifest = {
        "service_name": "digital-twin",
        "port": settings.port,
        "description": (
            "Digital Twin — unified house state model + 4-scenario energy simulation. "
            "Ingests HA sensor states, maintains room registry, runs 24h MILP-style projections."
        ),
        "endpoints": [
            {"method": "GET",  "path": "/health",                      "purpose": "Health check"},
            {"method": "GET",  "path": "/api/v1/state",                "purpose": "Current house state (rooms + energy)"},
            {"method": "GET",  "path": "/api/v1/state/energy",         "purpose": "Current energy snapshot"},
            {"method": "POST", "path": "/api/v1/state/refresh",        "purpose": "Force HA state refresh"},
            {"method": "GET",  "path": "/api/v1/rooms",                "purpose": "List room registry"},
            {"method": "POST", "path": "/api/v1/rooms",                "purpose": "Add a room"},
            {"method": "GET",  "path": "/api/v1/rooms/{room_id}",      "purpose": "Get a room"},
            {"method": "PATCH","path": "/api/v1/rooms/{room_id}",      "purpose": "Update a room"},
            {"method": "DELETE","path": "/api/v1/rooms/{room_id}",     "purpose": "Delete a room"},
            {"method": "GET",  "path": "/api/v1/scenarios",            "purpose": "List available scenarios"},
            {"method": "POST", "path": "/api/v1/simulate",             "purpose": "Run scenario simulation"},
            {"method": "GET",  "path": "/api/v1/simulate/latest",              "purpose": "Latest simulation report"},
            {"method": "GET",  "path": "/api/v1/optimize/recommendation",       "purpose": "Latest auto-optimization recommendation"},
            {"method": "POST", "path": "/api/v1/optimize/apply/{scenario_id}",  "purpose": "Apply and confirm a recommendation"},
        ],
        "nats_subjects": [
            {"subject": "digital.twin.state.updated",           "direction": "publish",   "purpose": "New HouseState snapshot"},
            {"subject": "digital.twin.simulation.done",         "direction": "publish",   "purpose": "New SimulationReport"},
            {"subject": "digital.twin.recommendation",          "direction": "publish",   "purpose": "Auto-optimization recommendation (hourly)"},
            {"subject": "digital.twin.recommendation.approved", "direction": "publish",   "purpose": "Approved recommendation — services should act"},
            {"subject": "orchestrator.command.digital-twin",    "direction": "subscribe", "purpose": "refresh / simulate commands"},
            {"subject": "energy.pv.forecast_updated",           "direction": "subscribe", "purpose": "Re-trigger simulation on new PV forecast"},
        ],
        "source_paths": [{"repo": "claude", "paths": ["services/digital-twin/"]}],
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{settings.oracle_url}/oracle/register", json=manifest)
        logger.info("digital_twin oracle_registered")
    except Exception as exc:
        logger.warning("digital_twin oracle_registration_failed error=%s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ingester, _pv_ingester
    _ingester = HAStateIngester()
    _pv_ingester = PVForecastIngester()

    # DB
    await db.init_pool(settings.db_url)
    await room_registry.seed_defaults_if_empty()

    # NATS
    await _nats_connect()

    # Initial state fetch
    asyncio.create_task(_refresh_state())
    asyncio.create_task(_run_auto_simulation())
    asyncio.create_task(_periodic_refresh())
    asyncio.create_task(
        run_optimizer_loop(
            get_energy_state=_get_current_energy,
            get_pv_forecast=_get_pv_forecast,
            publish=_nats_publish,
            **_sim_kwargs(),
        )
    )

    # Oracle
    asyncio.create_task(_register_with_oracle())

    yield

    if _nats_client is not None and not _nats_client.is_closed:
        await _nats_client.drain()
    await db.close_pool()


app = FastAPI(
    title="Digital Twin",
    description="House + Energy + Life digital twin with scenario simulation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        db_connected=db.get_pool() is not None,
        ha_reachable=_latest_house_state is not None,
    )


@app.get("/api/v1/state", response_model=HouseState)
async def get_state():
    if _latest_house_state is None:
        raise HTTPException(status_code=503, detail="State not yet populated — try again shortly")
    return _latest_house_state


@app.get("/api/v1/state/energy", response_model=EnergyState)
async def get_energy_state():
    if _latest_house_state is None:
        raise HTTPException(status_code=503, detail="State not yet populated")
    return _latest_house_state.energy


@app.post("/api/v1/state/refresh", status_code=202)
async def refresh_state():
    asyncio.create_task(_refresh_state())
    return {"status": "refresh_scheduled"}


# --- Rooms ---

@app.get("/api/v1/rooms", response_model=list[RoomResponse])
async def list_rooms():
    return await room_registry.list_rooms()


@app.post("/api/v1/rooms", response_model=RoomResponse, status_code=201)
async def create_room(data: RoomCreate):
    existing = await room_registry.get_room(data.room_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Room '{data.room_id}' already exists")
    try:
        return await room_registry.create_room(data)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str):
    room = await room_registry.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return room


@app.patch("/api/v1/rooms/{room_id}", response_model=RoomResponse)
async def update_room(room_id: str, data: RoomUpdate):
    room = await room_registry.update_room(room_id, data)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return room


@app.delete("/api/v1/rooms/{room_id}", status_code=204)
async def delete_room(room_id: str):
    deleted = await room_registry.delete_room(room_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")


# --- Scenarios & Simulation ---

@app.get("/api/v1/scenarios")
async def list_scenarios():
    return [
        {"id": s.value, "name": SCENARIO_LABELS[s]}
        for s in ScenarioID
    ]


@app.post("/api/v1/simulate", response_model=SimulationReport)
async def simulate(request: SimulationRequest):
    """Run scenario simulation with the provided request parameters."""
    # Use cached energy state if available
    energy = (
        _latest_house_state.energy
        if _latest_house_state
        else EnergyState()
    )
    pv_forecast: list[float]
    if request.pv_forecast_kwh:
        pv_forecast = request.pv_forecast_kwh
    elif _pv_ingester:
        pv_forecast = await _pv_ingester.fetch_24h_kwh(
            current_pv_w=energy.pv_total_power_w
        )
    else:
        from .state_ingestion import _shape_forecast
        pv_forecast = _shape_forecast(5.0)

    report = run_simulation(
        request=request,
        energy_state=energy,
        pv_forecast_kwh=pv_forecast,
        **_sim_kwargs(),
    )

    # Cache result
    global _latest_simulation
    _latest_simulation = report
    return report


@app.get("/api/v1/simulate/latest", response_model=SimulationReport)
async def get_latest_simulation():
    if _latest_simulation is None:
        raise HTTPException(status_code=404, detail="No simulation has run yet")
    return _latest_simulation


# --- Optimization ---

@app.get("/api/v1/optimize/recommendation")
async def get_recommendation():
    """Return the latest auto-optimization recommendation, or 404 if none available."""
    rec = get_latest_recommendation()
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail="No recommendation available — optimizer has not yet found a better scenario",
        )
    return rec.to_dict()


@app.post("/api/v1/optimize/apply/{scenario_id}", status_code=202)
async def apply_recommendation(scenario_id: str):
    """Accept a recommendation and trigger the corresponding actions via NATS."""
    rec = get_latest_recommendation()
    if rec is None:
        raise HTTPException(status_code=404, detail="No pending recommendation")
    if rec.scenario_id != scenario_id.upper():
        raise HTTPException(
            status_code=409,
            detail=f"Pending recommendation is for scenario {rec.scenario_id}, not {scenario_id}",
        )
    await _nats_publish(
        "digital.twin.recommendation.approved",
        {"scenario_id": scenario_id.upper(), "actions": rec.actions},
    )
    logger.info("recommendation_applied scenario=%s", scenario_id)
    return {"status": "accepted", "scenario_id": scenario_id.upper()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "digital_twin.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
