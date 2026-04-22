"""Publish PV surplus signals as HA sensors via NATS (#1045).

Publishes to NATS subject: energy.hems.pv_signals
HA auto-discovery via ha.discovery.sensor.hems_pv_*/config (nats-mqtt-bridge
forwards retained discovery messages to MQTT homeassistant/…/config).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.nats_client import NatsPublisher

logger = logging.getLogger(__name__)

HA_DISCOVERY_PREFIX = "homeassistant"
HEMS_NATS_SUBJECT = "energy.hems.pv_signals"
HEMS_MQTT_TOPIC = "homelab/hems/pv_signals"  # bridge target — do not publish directly

PV_SENSORS = [
    {"id": "pv_surplus_w", "name": "PV Surplus", "unit": "W", "device_class": "power"},
    {
        "id": "pv_self_consumption",
        "name": "PV Self Consumption",
        "unit": "%",
        "device_class": None,
    },
    {
        "id": "ev_charging_w",
        "name": "EV Charging Power",
        "unit": "W",
        "device_class": "power",
    },
    {
        "id": "dhw_pv_active",
        "name": "DHW PV Opportunistic",
        "unit": None,
        "device_class": "enum",
    },
]


async def publish_pv_signals(
    nats: "NatsPublisher",
    allocations: dict,
    pv_total_w: float,
    house_w: float,
) -> None:
    """Publish PV allocation signals to NATS for HA (via nats-mqtt-bridge)."""
    surplus = pv_total_w - house_w
    ev_w = allocations.get("ev_charging", 0.0)
    dhw_active = allocations.get("dhw_heating", 0.0) > 0
    self_consumption = (
        (pv_total_w - allocations.get("grid_export_w", 0)) / max(pv_total_w, 1)
    ) * 100

    payload = {
        "pv_surplus_w": round(surplus, 1),
        "pv_self_consumption": round(self_consumption, 1),
        "ev_charging_w": round(ev_w, 1),
        "dhw_pv_active": dhw_active,
    }

    try:
        await nats.publish(HEMS_NATS_SUBJECT, payload)
        logger.debug("Published PV signals via NATS: %s", payload)
    except Exception as e:
        logger.warning("Failed to publish PV signals: %s", e)


async def publish_ha_discovery(nats: "NatsPublisher") -> None:
    """Publish HA auto-discovery config for PV sensors via NATS."""
    for sensor in PV_SENSORS:
        config = {
            "name": f"HEMS {sensor['name']}",
            "unique_id": f"hems_{sensor['id']}",
            "state_topic": HEMS_MQTT_TOPIC,
            "value_template": f"{{{{ value_json.{sensor['id']} }}}}",
            "device": {
                "identifiers": ["hems_controller"],
                "name": "HEMS Controller",
            },
        }
        if sensor["unit"]:
            config["unit_of_measurement"] = sensor["unit"]
        if sensor["device_class"]:
            config["device_class"] = sensor["device_class"]

        subject = f"ha.discovery.sensor.hems_{sensor['id']}.config"
        try:
            await nats.publish(subject, config)
        except Exception as e:
            logger.warning("HA discovery publish failed for %s: %s", sensor["id"], e)
