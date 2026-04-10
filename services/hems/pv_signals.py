"""Publish PV surplus signals as HA sensors (#1045).

Publishes to MQTT topic: homelab/hems/pv_signals
HA auto-discovery under homeassistant/sensor/hems_pv_*/config
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

HA_DISCOVERY_PREFIX = "homeassistant"
HEMS_TOPIC_PREFIX = "homelab/hems"

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
    mqtt_client: Any,
    allocations: dict,
    pv_total_w: float,
    house_w: float,
) -> None:
    """Publish PV allocation signals to MQTT for HA."""
    surplus = pv_total_w - house_w
    ev_w = allocations.get("ev_charging", 0.0)
    dhw_active = allocations.get("dhw_heating", 0.0) > 0
    self_consumption = (
        (pv_total_w - allocations.get("grid_export_w", 0)) / max(pv_total_w, 1)
    ) * 100

    state_topic = f"{HEMS_TOPIC_PREFIX}/pv_signals"
    payload = {
        "pv_surplus_w": round(surplus, 1),
        "pv_self_consumption": round(self_consumption, 1),
        "ev_charging_w": round(ev_w, 1),
        "dhw_pv_active": dhw_active,
    }

    try:
        await mqtt_client.publish(state_topic, json.dumps(payload), retain=True)
        logger.debug("Published PV signals: %s", payload)
    except Exception as e:
        logger.warning("Failed to publish PV signals: %s", e)


async def publish_ha_discovery(mqtt_client: Any) -> None:
    """Publish HA auto-discovery config for PV sensors."""
    for sensor in PV_SENSORS:
        config = {
            "name": f"HEMS {sensor['name']}",
            "unique_id": f"hems_{sensor['id']}",
            "state_topic": f"{HEMS_TOPIC_PREFIX}/pv_signals",
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

        topic = f"{HA_DISCOVERY_PREFIX}/sensor/hems_{sensor['id']}/config"
        try:
            await mqtt_client.publish(topic, json.dumps(config), retain=True)
        except Exception as e:
            logger.warning("HA discovery publish failed for %s: %s", sensor["id"], e)
