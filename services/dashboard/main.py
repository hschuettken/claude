"""Dashboard service — NiceGUI web interface for homelab monitoring & control.

Provides:
- Real-time energy overview (PV, grid, battery, house, EV)
- Service health monitoring via NATS heartbeats
- Home Assistant entity controls (charge mode, switches, actions)
- Chat with the orchestrator via NATS
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from nicegui import app, ui

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.nats_client import NatsPublisher

from config import DashboardSettings
from state import DashboardState

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------

settings = DashboardSettings()
logger = get_logger("dashboard")
state = DashboardState()
_start_time = time.monotonic()

# Clients
ha = HomeAssistantClient(url=settings.ha_url, token=settings.ha_token)
influx = InfluxClient(
    url=settings.influxdb_url,
    token=settings.influxdb_token,
    org=settings.influxdb_org,
)
nats = NatsPublisher(url=settings.nats_url)

# ---------------------------------------------------------------------------
# NATS message handlers (async)
# ---------------------------------------------------------------------------


async def _on_heartbeat_nats(subject: str, payload: dict[str, Any]) -> None:
    service = payload.get("service", "unknown")
    state.update_service(service, payload)


async def _on_pv_update_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_pv_forecast(payload)
    logger.debug("pv_forecast_update_received")


async def _on_ev_charging_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_ev_charging(payload)


async def _on_ev_plan_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_ev_forecast(payload)


async def _on_ev_vehicle_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_ev_vehicle(payload)


async def _on_orchestrator_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_orchestrator(payload)


async def _on_health_status_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_health(payload)


async def _on_chat_response_nats(subject: str, payload: dict[str, Any]) -> None:
    request_id = payload.get("request_id", "")
    response = payload.get("response", "")
    if response:
        state.receive_chat_response(request_id, response)
        logger.info("chat_response_received", request_id=request_id)


async def _on_dt_simulation_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_digital_twin_simulation(payload)
    logger.debug("digital_twin_simulation_updated")


async def _on_dt_state_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_digital_twin_house_state(payload)
    logger.debug("digital_twin_state_updated")


async def _on_dt_recommendation_nats(subject: str, payload: dict[str, Any]) -> None:
    state.update_digital_twin_recommendation(payload)
    logger.info("digital_twin_recommendation_received", scenario=payload.get("scenario_id"))


# ---------------------------------------------------------------------------
# HA polling
# ---------------------------------------------------------------------------

_POLL_ENTITIES: list[str] = [
    settings.pv_power_entity,
    settings.grid_power_entity,
    settings.battery_power_entity,
    settings.battery_soc_entity,
    settings.house_power_entity,
    settings.inverter_power_entity,
    settings.ev_charge_power_entity,
    settings.ev_soc_entity,
    settings.ev_range_entity,
    settings.ev_plug_entity,
    settings.ev_charge_mode_entity,
    settings.ev_target_soc_entity,
    settings.ev_departure_time_entity,
    settings.ev_full_by_morning_entity,
    settings.pv_forecast_today_entity,
    settings.pv_forecast_tomorrow_entity,
    settings.pv_forecast_remaining_entity,
    settings.safe_mode_entity_id,
]


async def _ha_poll_loop() -> None:
    """Periodically fetch HA entity states."""
    while True:
        for entity_id in _POLL_ENTITIES:
            try:
                data = await ha.get_state(entity_id)
                state.update_ha_entity(entity_id, data)
            except Exception:
                logger.debug("ha_poll_failed", entity_id=entity_id)
        await asyncio.sleep(settings.ha_poll_interval)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def _heartbeat_loop() -> None:
    """Publish dashboard heartbeat to NATS."""
    await asyncio.sleep(5)
    while True:
        try:
            await nats.publish(
                "heartbeat.dashboard",
                {
                    "status": "online",
                    "service": "dashboard",
                    "uptime_seconds": round(time.monotonic() - _start_time, 1),
                    "memory_mb": _get_memory_mb(),
                },
            )
        except Exception:
            pass
        await asyncio.sleep(60)


def _get_memory_mb() -> float:
    """Read RSS from /proc (Linux)."""
    import os

    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Oracle Registration
# ---------------------------------------------------------------------------


async def _register_with_oracle() -> None:
    """Best-effort Oracle registration. Non-critical — service must start even if Oracle is down."""
    try:
        manifest = {
            "service_name": "energy-dashboard",
            "port": 8085,
            "description": "NiceGUI energy cockpit — PV, EV, grid, battery visualization",
            "endpoints": [
                {"method": "GET", "path": "/_health", "purpose": "Health check"},
                {"method": "GET", "path": "/", "purpose": "Dashboard home page"},
                {
                    "method": "GET",
                    "path": "/services",
                    "purpose": "Services status page",
                },
                {
                    "method": "GET",
                    "path": "/controls",
                    "purpose": "EV charging controls page",
                },
                {
                    "method": "GET",
                    "path": "/chat",
                    "purpose": "Chat with orchestrator page",
                },
                {
                    "method": "GET",
                    "path": "/digital-twin",
                    "purpose": "Digital Twin scenario comparison + thermal map page",
                },
                {
                    "method": "GET",
                    "path": "/agent-economy",
                    "purpose": "Agent Economy registry, tasks, budget, and spawn requests page",
                },
            ],
            "nats_subjects": [
                "heartbeat.dashboard",
                "heartbeat.>",
                "energy.pv.forecast.updated",
                "energy.ev.charging.status",
                "energy.ev.forecast.plan",
                "energy.ev.forecast.vehicle",
                "services.orchestrator.activity",
                "services.health-monitor.status",
                "services.dashboard.chat_response",
                "digital.twin.simulation.done",
                "digital.twin.state.updated",
                "digital.twin.recommendation",
            ],
            "source_paths": [
                {"repo": "claude", "paths": ["services/dashboard/"]},
            ],
        }
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HA NATS auto-discovery
# ---------------------------------------------------------------------------


async def _register_ha_discovery() -> None:
    """Register dashboard entities in Home Assistant via NATS ha.discovery.*"""

    device = {
        "identifiers": ["homelab_dashboard"],
        "name": "Homelab Dashboard",
        "manufacturer": "Homelab",
        "model": "dashboard",
    }
    node = "dashboard"
    heartbeat_topic = "homelab/dashboard/heartbeat"

    await nats.publish(
        f"ha.discovery.binary_sensor.{node}.service_status.config",
        {
            "name": "Dashboard Status",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
            "device_class": "connectivity",
            "expire_after": 180,
            "unique_id": f"{node}_service_status",
        },
    )

    await nats.publish(
        f"ha.discovery.sensor.{node}.uptime.config",
        {
            "name": "Dashboard Uptime",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ value_json.uptime_seconds }}",
            "unit_of_measurement": "s",
            "icon": "mdi:timer-outline",
            "entity_category": "diagnostic",
            "unique_id": f"{node}_uptime",
        },
    )

    logger.info("ha_discovery_published", entity_count=2)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@app.on_startup
async def on_startup() -> None:
    logger.info("dashboard_starting", port=settings.dashboard_port)

    # Register with Oracle (non-blocking)
    asyncio.create_task(_register_with_oracle())

    # Connect NATS and set up subscriptions
    await nats.connect()
    await nats.subscribe_json("heartbeat.>", _on_heartbeat_nats)
    await nats.subscribe_json("energy.pv.forecast.updated", _on_pv_update_nats)
    await nats.subscribe_json("energy.ev.charging.status", _on_ev_charging_nats)
    await nats.subscribe_json("energy.ev.forecast.plan", _on_ev_plan_nats)
    await nats.subscribe_json("energy.ev.forecast.vehicle", _on_ev_vehicle_nats)
    await nats.subscribe_json("services.orchestrator.activity", _on_orchestrator_nats)
    await nats.subscribe_json("services.health-monitor.status", _on_health_status_nats)
    await nats.subscribe_json(
        "services.dashboard.chat_response", _on_chat_response_nats
    )
    await nats.subscribe_json("digital.twin.simulation.done", _on_dt_simulation_nats)
    await nats.subscribe_json("digital.twin.state.updated", _on_dt_state_nats)
    await nats.subscribe_json("digital.twin.recommendation", _on_dt_recommendation_nats)

    await _register_ha_discovery()
    asyncio.create_task(_ha_poll_loop())
    asyncio.create_task(_heartbeat_loop())
    logger.info("dashboard_ready", port=settings.dashboard_port)


@app.on_shutdown
async def on_shutdown() -> None:
    logger.info("dashboard_shutting_down")
    try:
        await nats.publish(
            "heartbeat.dashboard",
            {"status": "offline", "service": "dashboard"},
        )
    except Exception:
        pass
    await nats.close()
    await ha.close()
    influx.close()
    logger.info("dashboard_stopped")


# ---------------------------------------------------------------------------
# Health endpoint (for Docker healthcheck)
# ---------------------------------------------------------------------------


@app.get("/_health")
def health_endpoint() -> dict[str, str]:
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Register page modules
# ---------------------------------------------------------------------------

import page_agent_economy  # noqa: E402
import page_chat  # noqa: E402
import page_cognitive  # noqa: E402
import page_controls  # noqa: E402
import page_digital_twin  # noqa: E402
import page_family  # noqa: E402
import page_home  # noqa: E402
import page_infra  # noqa: E402
import page_life_nav  # noqa: E402
import page_services  # noqa: E402

page_home.setup(state, settings)
page_services.setup(state, settings)
page_controls.setup(state, settings, ha, nats)
page_digital_twin.setup(state, settings)
page_life_nav.setup(state, settings)
page_family.setup(state, settings)
page_cognitive.setup(state, settings)
page_agent_economy.setup(state, settings)
page_infra.setup(state, settings)
page_chat.setup(state, settings, nats)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

ui.run(
    port=settings.dashboard_port,
    title=settings.dashboard_title,
    dark=True,
    show=False,
    reload=False,
    favicon="\U0001f3e0",
    binding_refresh_interval=0.5,
)
