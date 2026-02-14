"""Dashboard service — NiceGUI web interface for homelab monitoring & control.

Provides:
- Real-time energy overview (PV, grid, battery, house, EV)
- Service health monitoring via MQTT heartbeats
- Home Assistant entity controls (charge mode, switches, actions)
- Chat with the orchestrator via MQTT
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nicegui import app, ui

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.mqtt_client import MQTTClient

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
mqtt = MQTTClient(
    host=settings.mqtt_host,
    port=settings.mqtt_port,
    client_id="dashboard",
    username=settings.mqtt_username,
    password=settings.mqtt_password,
)

# ---------------------------------------------------------------------------
# MQTT message handlers
# ---------------------------------------------------------------------------


def _on_heartbeat(topic: str, payload: dict[str, Any]) -> None:
    service = payload.get("service", "unknown")
    state.update_service(service, payload)


def _on_pv_update(topic: str, payload: dict[str, Any]) -> None:
    state.update_pv_forecast(payload)
    logger.debug("pv_forecast_update_received")


def _on_ev_charging(topic: str, payload: dict[str, Any]) -> None:
    state.update_ev_charging(payload)


def _on_ev_plan(topic: str, payload: dict[str, Any]) -> None:
    state.update_ev_forecast(payload)


def _on_ev_vehicle(topic: str, payload: dict[str, Any]) -> None:
    state.update_ev_vehicle(payload)


def _on_orchestrator(topic: str, payload: dict[str, Any]) -> None:
    state.update_orchestrator(payload)


def _on_health_status(topic: str, payload: dict[str, Any]) -> None:
    state.update_health(payload)


def _on_chat_response(topic: str, payload: dict[str, Any]) -> None:
    request_id = payload.get("request_id", "")
    response = payload.get("response", "")
    if response:
        state.receive_chat_response(request_id, response)
        logger.info("chat_response_received", request_id=request_id)


# Register all subscriptions before connecting
mqtt.subscribe("homelab/+/heartbeat", _on_heartbeat)
mqtt.subscribe("homelab/pv-forecast/updated", _on_pv_update)
mqtt.subscribe("homelab/smart-ev-charging/status", _on_ev_charging)
mqtt.subscribe("homelab/ev-forecast/plan", _on_ev_plan)
mqtt.subscribe("homelab/ev-forecast/vehicle", _on_ev_vehicle)
mqtt.subscribe("homelab/orchestrator/activity", _on_orchestrator)
mqtt.subscribe("homelab/health-monitor/status", _on_health_status)
mqtt.subscribe("homelab/dashboard/chat-response", _on_chat_response)

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
    """Publish dashboard heartbeat to MQTT."""
    await asyncio.sleep(5)
    while True:
        try:
            mqtt.publish(
                "homelab/dashboard/heartbeat",
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
# HA MQTT auto-discovery
# ---------------------------------------------------------------------------


def _register_ha_discovery() -> None:
    """Register dashboard entities in Home Assistant."""
    device = {
        "identifiers": ["homelab_dashboard"],
        "name": "Homelab Dashboard",
        "manufacturer": "Homelab",
        "model": "dashboard",
    }
    node = "dashboard"
    heartbeat_topic = "homelab/dashboard/heartbeat"

    mqtt.publish_ha_discovery(
        "binary_sensor",
        "service_status",
        node_id=node,
        config={
            "name": "Dashboard Status",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
            "device_class": "connectivity",
            "expire_after": 180,
        },
    )

    mqtt.publish_ha_discovery(
        "sensor",
        "uptime",
        node_id=node,
        config={
            "name": "Dashboard Uptime",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ value_json.uptime_seconds }}",
            "unit_of_measurement": "s",
            "icon": "mdi:timer-outline",
            "entity_category": "diagnostic",
        },
    )

    logger.info("ha_discovery_registered", entity_count=2)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@app.on_startup
async def on_startup() -> None:
    logger.info("dashboard_starting", port=settings.dashboard_port)
    mqtt.connect_background()
    _register_ha_discovery()
    asyncio.create_task(_ha_poll_loop())
    asyncio.create_task(_heartbeat_loop())
    logger.info("dashboard_ready", port=settings.dashboard_port)


@app.on_shutdown
async def on_shutdown() -> None:
    logger.info("dashboard_shutting_down")
    try:
        mqtt.publish(
            "homelab/dashboard/heartbeat",
            {"status": "offline", "service": "dashboard"},
        )
    except Exception:
        pass
    mqtt.disconnect()
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

import page_chat  # noqa: E402
import page_controls  # noqa: E402
import page_home  # noqa: E402
import page_services  # noqa: E402

page_home.setup(state, settings)
page_services.setup(state, settings)
page_controls.setup(state, settings, ha, mqtt)
page_chat.setup(state, settings, mqtt)

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
