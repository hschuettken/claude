"""Base service class that handles boilerplate setup.

Every service can inherit from this to get config, logging, HA client,
InfluxDB client, and MQTT set up automatically.

Usage:
    import asyncio
    from shared.service import BaseService

    class MyService(BaseService):
        name = "my-service"

        async def run(self) -> None:
            # self.settings, self.logger, self.ha, self.influx, self.mqtt
            # are all ready to use
            state = await self.ha.get_state("sensor.temperature")
            self.logger.info("temperature", value=state["state"])

    if __name__ == "__main__":
        service = MyService()
        asyncio.run(service.start())
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from shared.config import Settings
from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.logging import get_logger
from shared.mqtt_client import MQTTClient


class BaseService:
    """Base class for homelab automation services."""

    name: str = "unnamed-service"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.logger = get_logger(self.name)
        self._shutdown_event = asyncio.Event()

        # Clients — initialized lazily; override in subclass if not needed
        self.ha = HomeAssistantClient(
            url=self.settings.ha_url,
            token=self.settings.ha_token,
        )
        self.influx = InfluxClient(
            url=self.settings.influxdb_url,
            token=self.settings.influxdb_token,
            org=self.settings.influxdb_org,
        )
        self.mqtt = MQTTClient(
            host=self.settings.mqtt_host,
            port=self.settings.mqtt_port,
            client_id=self.name,
            username=self.settings.mqtt_username,
            password=self.settings.mqtt_password,
        )

    async def run(self) -> None:
        """Override this method with your service logic."""
        raise NotImplementedError("Subclasses must implement run()")

    async def start(self) -> None:
        """Start the service with graceful shutdown handling."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        self.logger.info("service_starting", service=self.name)
        try:
            await self.run()
        except asyncio.CancelledError:
            self.logger.info("service_cancelled")
        finally:
            await self.shutdown()

    def _handle_shutdown(self) -> None:
        self.logger.info("shutdown_signal_received")
        self._shutdown_event.set()

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.logger.info("service_shutting_down")
        await self.ha.close()
        self.influx.close()
        self.mqtt.disconnect()
        self.logger.info("service_stopped")

    async def wait_for_shutdown(self) -> None:
        """Await this in your run() to block until shutdown signal."""
        await self._shutdown_event.wait()

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event on the service's MQTT topic."""
        topic = f"homelab/{self.name}/{event_type}"
        self.mqtt.publish(topic, data)
