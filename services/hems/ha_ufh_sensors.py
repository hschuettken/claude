"""Home Assistant UFH (Underfloor Heating) per-circuit power sensors.

Creates NATS-based power sensors for each UFH circuit room (wohnzimmer, schlafzimmer,
kinderzimmer, buero, kueche, esszimmer, bad, flur) via Home Assistant MQTT auto-discovery
forwarded through the nats-mqtt-bridge.

Publishes current power consumption to NATS subject
`energy.hems.circuits.{circuit_id}.power` (watts).

HA auto-discovery payloads are published to `ha.discovery.sensor.{object_id}.config`
and forwarded to MQTT `homeassistant/sensor/...` by the nats-mqtt-bridge.

Usage:
    from ha_ufh_sensors import UFHSensorProvisioner
    from shared.nats_client import NatsPublisher

    publisher = NatsPublisher(url="nats://192.168.0.50:4222")
    await publisher.connect()

    provisioner = UFHSensorProvisioner(publisher)
    sensor_ids = await provisioner.provision_template_sensors()

    # Later, publish power reading
    await provisioner.publish_circuit_power("wohnzimmer", 2500.5)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.ha_ufh_sensors")

NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

# UFH circuit definitions: 8 rooms with friendly names and climate entity IDs
CIRCUIT_DEFINITIONS = [
    {
        "id": "wohnzimmer",
        "name": "Wohnzimmer UFH",
        "entity": "climate.wohnzimmer",
    },
    {
        "id": "schlafzimmer",
        "name": "Schlafzimmer UFH",
        "entity": "climate.schlafzimmer",
    },
    {
        "id": "kinderzimmer",
        "name": "Kinderzimmer UFH",
        "entity": "climate.kinderzimmer",
    },
    {
        "id": "buero",
        "name": "Büro UFH",
        "entity": "climate.buero",
    },
    {
        "id": "kueche",
        "name": "Küche UFH",
        "entity": "climate.kueche",
    },
    {
        "id": "esszimmer",
        "name": "Esszimmer UFH",
        "entity": "climate.esszimmer",
    },
    {
        "id": "bad",
        "name": "Bad UFH",
        "entity": "climate.bad",
    },
    {
        "id": "flur",
        "name": "Flur UFH",
        "entity": "climate.flur",
    },
]


class UFHSensorProvisioner:
    """Provisions UFH power sensors in Home Assistant via NATS auto-discovery."""

    def __init__(self, nats_publisher: NatsPublisher) -> None:
        """Initialize provisioner with NATS publisher.

        Args:
            nats_publisher: Connected NatsPublisher for publishing auto-discovery configs
        """
        self.nats = nats_publisher
        self._created_sensors: list[str] = []

    async def provision_template_sensors(self) -> list[str]:
        """Create UFH power sensors via NATS → HA MQTT auto-discovery.

        For each circuit, publishes an HA MQTT sensor discovery message that:
        - Listens to homelab/hems/circuits/{circuit_id}/power
        - Displays power in Watts with device_class="power"
        - Creates a unique entity per circuit

        Returns:
            List of created sensor entity IDs (e.g., ["sensor.ufh_wohnzimmer_power", ...])
        """
        self._created_sensors = []

        for circuit in CIRCUIT_DEFINITIONS:
            circuit_id = circuit["id"]
            friendly_name = circuit["name"]
            object_id = f"ufh_{circuit_id}_power"

            # Build HA MQTT discovery message
            discovery_payload: dict[str, Any] = {
                "name": f"{friendly_name} Power",
                "unique_id": object_id,
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "state_topic": f"homelab/hems/circuits/{circuit_id}/power",
                "availability_topic": "homelab/hems/heartbeat/state",
                "availability_payload_available": "online",
                "availability_payload_not_available": "offline",
                "icon": "mdi:heating-element",
                "device": {
                    "identifiers": [f"hems_ufh_{circuit_id}"],
                    "name": friendly_name,
                    "manufacturer": "HEMS",
                    "model": "UFH Circuit",
                },
            }

            subject = f"ha.discovery.sensor.{object_id}.config"

            try:
                self.nats.publish_sync(subject, discovery_payload)
                entity_id = f"sensor.{object_id}"
                self._created_sensors.append(entity_id)
                logger.info(
                    "ufh_sensor_published",
                    circuit_id=circuit_id,
                    entity_id=entity_id,
                    subject=subject,
                )
            except Exception as exc:
                logger.exception(
                    "ufh_sensor_publish_failed",
                    circuit_id=circuit_id,
                    error=str(exc),
                )

        return self._created_sensors

    async def publish_circuit_power(self, circuit_id: str, watts: float) -> None:
        """Publish current power consumption for a circuit via NATS.

        Args:
            circuit_id: Circuit identifier (e.g., "wohnzimmer")
            watts: Power consumption in watts (float)
        """
        subject = f"energy.hems.circuits.{circuit_id}.power"
        try:
            if not self.nats.connected:
                await self.nats.connect()
            await self.nats.publish(subject, {"watts": watts, "circuit_id": circuit_id})
            logger.debug("circuit_power_published", circuit_id=circuit_id, watts=watts)
        except Exception as exc:
            logger.exception(
                "circuit_power_publish_failed",
                circuit_id=circuit_id,
                watts=watts,
                error=str(exc),
            )
