"""Base service class that handles boilerplate setup.

Every service can inherit from this to get config, logging, HA client,
InfluxDB client, and MQTT set up automatically.

Includes automatic MQTT heartbeat — every service publishes its status
to `homelab/{service-name}/heartbeat` periodically. Override `health_check()`
to add custom health logic.

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
import os
import signal
import time
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
        self._start_time: float = time.monotonic()
        self._heartbeat_task: asyncio.Task | None = None

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

        # Start heartbeat in background
        if self.settings.heartbeat_interval_seconds > 0:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

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
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        # Publish offline status before disconnecting
        try:
            self.publish("heartbeat", {"status": "offline", "service": self.name})
        except Exception:
            pass
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

    # --- Heartbeat ---

    def health_check(self) -> dict[str, Any]:
        """Override to add custom health info to the heartbeat.

        Return a dict of key-value pairs that get merged into the
        heartbeat payload. Return {"status": "degraded"} or
        {"status": "unhealthy"} to signal problems.

        Example:
            def health_check(self):
                if self.last_forecast_age > 7200:
                    return {"status": "degraded", "reason": "forecast stale"}
                return {"last_forecast": self.last_forecast_time}
        """
        return {}

    def _get_uptime_seconds(self) -> float:
        return round(time.monotonic() - self._start_time, 1)

    def _get_memory_mb(self) -> float:
        """Get RSS memory usage in MB (Linux)."""
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            pass
        return 0.0

    async def _heartbeat_loop(self) -> None:
        """Periodically publish heartbeat to MQTT."""
        interval = self.settings.heartbeat_interval_seconds
        # Small initial delay so the service has time to connect MQTT
        await asyncio.sleep(min(5, interval))

        while not self._shutdown_event.is_set():
            try:
                payload: dict[str, Any] = {
                    "status": "online",
                    "service": self.name,
                    "uptime_seconds": self._get_uptime_seconds(),
                    "memory_mb": self._get_memory_mb(),
                }
                # Merge custom health check
                custom = self.health_check()
                if custom:
                    payload.update(custom)

                self.publish("heartbeat", payload)
            except Exception:
                self.logger.debug("heartbeat_publish_failed")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=interval
                )
                break  # shutdown event was set
            except asyncio.TimeoutError:
                pass  # normal — just means the interval elapsed
