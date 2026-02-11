"""Example service — use this as a template for new services.

This service demonstrates:
  - Inheriting from BaseService for automatic setup
  - Subscribing to MQTT topics
  - Querying Home Assistant
  - Publishing MQTT events
  - Healthcheck file for Docker HEALTHCHECK
  - Listening to orchestrator commands
  - Graceful shutdown
"""

import asyncio
import time
from pathlib import Path

from shared.service import BaseService

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class ExampleService(BaseService):
    name = "example-service"

    async def run(self) -> None:
        self.logger.info("example_service_started")

        # Connect MQTT in background thread
        self.mqtt.connect_background()

        # Subscribe to a topic
        self.mqtt.subscribe(
            "homelab/#",
            lambda topic, payload: self.logger.info(
                "mqtt_message", topic=topic, payload=payload
            ),
        )

        # Listen to orchestrator commands
        self.mqtt.subscribe(
            "homelab/orchestrator/command/example-service",
            self._on_orchestrator_command,
        )

        # Example: read a HA sensor on startup
        # state = await self.ha.get_state("sensor.temperature_living_room")
        # self.logger.info("sensor_state", state=state["state"])

        # Example: query InfluxDB for the last hour
        # records = self.influx.query_records(
        #     bucket=self.settings.influxdb_bucket,
        #     entity_id="sensor.temperature_living_room",
        #     range_start="-1h",
        # )
        # for r in records:
        #     self.logger.info("influx_record", time=r["_time"], value=r["_value"])

        # Example: publish an event
        self.publish("started", {"status": "ok"})

        # Touch healthcheck on startup
        self._touch_healthcheck()

        # Keep running until shutdown signal
        await self.wait_for_shutdown()

    def _on_orchestrator_command(self, topic: str, payload: dict) -> None:
        """Handle commands from the orchestrator service."""
        command = payload.get("command", "")
        self.logger.info("orchestrator_command", command=command)

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass


if __name__ == "__main__":
    service = ExampleService()
    asyncio.run(service.start())
