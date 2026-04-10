"""Home Assistant UFH (Underfloor Heating) per-circuit power sensors.

Creates MQTT-based power sensors for each UFH circuit room (wohnzimmer, schlafzimmer,
kinderzimmer, buero, kueche, esszimmer, bad, flur) via Home Assistant MQTT auto-discovery.

Publishes current power consumption to `homelab/hems/circuits/{circuit_id}/power` (watts).

Usage:
    from ha_ufh_sensors import UFHSensorProvisioner
    from shared.mqtt_client import MQTTClient
    from config import HEMSSettings

    settings = HEMSSettings()
    mqtt = MQTTClient(host="192.168.0.73", port=1883, client_id="hems")

    provisioner = UFHSensorProvisioner(mqtt)
    sensor_ids = await provisioner.provision_template_sensors()

    # Later, publish power reading
    await provisioner.publish_circuit_power("wohnzimmer", 2500.5)
"""

from __future__ import annotations

import logging

from shared.mqtt_client import MQTTClient

logger = logging.getLogger("hems.ha_ufh_sensors")

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
    """Provisions UFH power sensors in Home Assistant via MQTT discovery."""

    def __init__(self, mqtt_client: MQTTClient) -> None:
        """Initialize provisioner with MQTT client.

        Args:
            mqtt_client: Connected MQTTClient for publishing auto-discovery configs
        """
        self.mqtt = mqtt_client
        self._created_sensors: list[str] = []

    async def provision_template_sensors(self) -> list[str]:
        """Create UFH power sensors via MQTT auto-discovery.

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

            # Build HA MQTT discovery message
            discovery_payload = {
                "name": f"{friendly_name} Power",
                "unique_id": f"ufh_{circuit_id}_power",
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

            discovery_topic = f"homeassistant/sensor/ufh_{circuit_id}_power/config"

            try:
                self.mqtt.publish(discovery_topic, discovery_payload)
                entity_id = f"sensor.ufh_{circuit_id}_power"
                self._created_sensors.append(entity_id)
                logger.info(
                    "ufh_sensor_published",
                    circuit_id=circuit_id,
                    entity_id=entity_id,
                    topic=discovery_topic,
                )
            except Exception as exc:
                logger.exception(
                    "ufh_sensor_publish_failed",
                    circuit_id=circuit_id,
                    error=str(exc),
                )

        return self._created_sensors

    def publish_circuit_power(self, circuit_id: str, watts: float) -> None:
        """Publish current power consumption for a circuit.

        Args:
            circuit_id: Circuit identifier (e.g., "wohnzimmer")
            watts: Power consumption in watts (float)
        """
        topic = f"homelab/hems/circuits/{circuit_id}/power"
        try:
            self.mqtt.publish(topic, str(watts))
            logger.debug("circuit_power_published", circuit_id=circuit_id, watts=watts)
        except Exception as exc:
            logger.exception(
                "circuit_power_publish_failed",
                circuit_id=circuit_id,
                watts=watts,
                error=str(exc),
            )
