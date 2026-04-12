"""Home Assistant utility meters for per-room cumulative heating energy.

Creates NATS-based energy sensors for each UFH circuit that accumulate daily energy
consumption. Uses Home Assistant MQTT auto-discovery via the nats-mqtt-bridge.

Publishes daily cumulative energy to `homelab/hems/circuits/{circuit_id}/energy_daily` (kWh)
via NATS subject `energy.hems.circuits.{circuit_id}.energy_daily`.

HA auto-discovery payloads are published to `ha.discovery.sensor.{node_id}.{object_id}.config`
and forwarded to MQTT `homeassistant/sensor/...` by the nats-mqtt-bridge.

Usage:
    from ha_utility_meters import UtilityMeterProvisioner
    from shared.nats_client import NatsPublisher

    publisher = NatsPublisher(url="nats://192.168.0.50:4222")
    await publisher.connect()

    provisioner = UtilityMeterProvisioner(publisher)
    count = await provisioner.provision_utility_meters()

    # Later, publish daily energy reading
    await provisioner.publish_circuit_energy("wohnzimmer", 12.5)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.ha_utility_meters")

NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

# UFH circuit definitions for utility meters (same 8 rooms)
CIRCUIT_DEFINITIONS = [
    {
        "id": "wohnzimmer",
        "name": "Wohnzimmer UFH",
    },
    {
        "id": "schlafzimmer",
        "name": "Schlafzimmer UFH",
    },
    {
        "id": "kinderzimmer",
        "name": "Kinderzimmer UFH",
    },
    {
        "id": "buero",
        "name": "Büro UFH",
    },
    {
        "id": "kueche",
        "name": "Küche UFH",
    },
    {
        "id": "esszimmer",
        "name": "Esszimmer UFH",
    },
    {
        "id": "bad",
        "name": "Bad UFH",
    },
    {
        "id": "flur",
        "name": "Flur UFH",
    },
]


def _publish_ha_discovery_nats(
    publisher: NatsPublisher,
    component: str,
    object_id: str,
    config: dict[str, Any],
    node_id: str = "",
) -> None:
    """Publish HA auto-discovery config via NATS (nats-mqtt-bridge forwards to MQTT).

    Args:
        publisher: Connected NatsPublisher instance
        component: HA component type (e.g. "sensor")
        object_id: Object ID within the component (e.g. "ufh_wohnzimmer_energy_daily")
        config: HA discovery payload dict
        node_id: Optional node ID prefix for the subject
    """
    if "unique_id" not in config:
        config["unique_id"] = f"{node_id}_{object_id}" if node_id else object_id
    if node_id:
        subject = f"ha.discovery.{component}.{node_id}.{object_id}.config"
    else:
        subject = f"ha.discovery.{component}.{object_id}.config"
    publisher.publish_sync(subject, config)


class UtilityMeterProvisioner:
    """Provisions UFH energy utility meters in Home Assistant via NATS auto-discovery."""

    def __init__(self, nats_publisher: NatsPublisher) -> None:
        """Initialize provisioner with NATS publisher.

        Args:
            nats_publisher: Connected NatsPublisher for publishing auto-discovery configs
        """
        self.nats = nats_publisher
        self._created_meters: list[str] = []

    async def provision_utility_meters(self) -> int:
        """Create UFH energy utility meters via NATS → HA MQTT auto-discovery.

        For each circuit, publishes an HA MQTT sensor discovery message that:
        - Listens to homelab/hems/circuits/{circuit_id}/energy_daily
        - Displays energy in kWh with device_class="energy"
        - Uses state_class="total_increasing" for cumulative counters

        Returns:
            Count of meters created
        """
        self._created_meters = []

        for circuit in CIRCUIT_DEFINITIONS:
            circuit_id = circuit["id"]
            friendly_name = circuit["name"]
            object_id = f"ufh_{circuit_id}_energy_daily"

            # Build HA MQTT discovery message for energy sensor
            discovery_payload: dict[str, Any] = {
                "name": f"{friendly_name} Daily Energy",
                "unique_id": object_id,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
                "state_topic": f"homelab/hems/circuits/{circuit_id}/energy_daily",
                "availability_topic": "homelab/hems/heartbeat/state",
                "availability_payload_available": "online",
                "availability_payload_not_available": "offline",
                "icon": "mdi:counter",
                "device": {
                    "identifiers": [f"hems_ufh_{circuit_id}"],
                    "name": friendly_name,
                    "manufacturer": "HEMS",
                    "model": "UFH Circuit",
                },
            }

            try:
                _publish_ha_discovery_nats(
                    self.nats,
                    component="sensor",
                    object_id=object_id,
                    config=discovery_payload,
                )
                entity_id = f"sensor.{object_id}"
                self._created_meters.append(entity_id)
                logger.info(
                    "utility_meter_published",
                    circuit_id=circuit_id,
                    entity_id=entity_id,
                    subject=f"ha.discovery.sensor.{object_id}.config",
                )
            except Exception as exc:
                logger.exception(
                    "utility_meter_publish_failed",
                    circuit_id=circuit_id,
                    error=str(exc),
                )

        return len(self._created_meters)

    async def publish_circuit_energy(self, circuit_id: str, kwh: float) -> None:
        """Publish daily cumulative energy consumption for a circuit via NATS.

        Args:
            circuit_id: Circuit identifier (e.g., "wohnzimmer")
            kwh: Energy consumption in kilowatt-hours (float)
        """
        subject = f"energy.hems.circuits.{circuit_id}.energy_daily"
        try:
            if not self.nats.connected:
                await self.nats.connect()
            await self.nats.publish(subject, {"kwh": kwh, "circuit_id": circuit_id})
            logger.debug("circuit_energy_published", circuit_id=circuit_id, kwh=kwh)
        except Exception as exc:
            logger.exception(
                "circuit_energy_publish_failed",
                circuit_id=circuit_id,
                kwh=kwh,
                error=str(exc),
            )
