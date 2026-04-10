"""Home Assistant utility meters for per-room cumulative heating energy.

Creates MQTT-based energy sensors for each UFH circuit that accumulate daily energy
consumption. Uses Home Assistant MQTT auto-discovery.

Publishes daily cumulative energy to `homelab/hems/circuits/{circuit_id}/energy_daily` (kWh).

Usage:
    from ha_utility_meters import UtilityMeterProvisioner
    from shared.mqtt_client import MQTTClient
    from config import HEMSSettings

    settings = HEMSSettings()
    mqtt = MQTTClient(host="192.168.0.73", port=1883, client_id="hems")

    provisioner = UtilityMeterProvisioner(mqtt)
    count = await provisioner.provision_utility_meters()

    # Later, publish daily energy reading
    await provisioner.publish_circuit_energy("wohnzimmer", 12.5)
"""

from __future__ import annotations

import logging

from shared.mqtt_client import MQTTClient

logger = logging.getLogger("hems.ha_utility_meters")

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


class UtilityMeterProvisioner:
    """Provisions UFH energy utility meters in Home Assistant via MQTT discovery."""

    def __init__(self, mqtt_client: MQTTClient) -> None:
        """Initialize provisioner with MQTT client.

        Args:
            mqtt_client: Connected MQTTClient for publishing auto-discovery configs
        """
        self.mqtt = mqtt_client
        self._created_meters: list[str] = []

    async def provision_utility_meters(self) -> int:
        """Create UFH energy utility meters via MQTT auto-discovery.

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

            # Build HA MQTT discovery message for energy sensor
            discovery_payload = {
                "name": f"{friendly_name} Daily Energy",
                "unique_id": f"ufh_{circuit_id}_energy_daily",
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

            discovery_topic = (
                f"homeassistant/sensor/ufh_{circuit_id}_energy_daily/config"
            )

            try:
                self.mqtt.publish(discovery_topic, discovery_payload)
                entity_id = f"sensor.ufh_{circuit_id}_energy_daily"
                self._created_meters.append(entity_id)
                logger.info(
                    "utility_meter_published",
                    circuit_id=circuit_id,
                    entity_id=entity_id,
                    topic=discovery_topic,
                )
            except Exception as exc:
                logger.exception(
                    "utility_meter_publish_failed",
                    circuit_id=circuit_id,
                    error=str(exc),
                )

        return len(self._created_meters)

    def publish_circuit_energy(self, circuit_id: str, kwh: float) -> None:
        """Publish daily cumulative energy consumption for a circuit.

        Args:
            circuit_id: Circuit identifier (e.g., "wohnzimmer")
            kwh: Energy consumption in kilowatt-hours (float)
        """
        topic = f"homelab/hems/circuits/{circuit_id}/energy_daily"
        try:
            self.mqtt.publish(topic, str(kwh))
            logger.debug("circuit_energy_published", circuit_id=circuit_id, kwh=kwh)
        except Exception as exc:
            logger.exception(
                "circuit_energy_publish_failed",
                circuit_id=circuit_id,
                kwh=kwh,
                error=str(exc),
            )
