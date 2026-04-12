"""HEMS heartbeat publisher for HA watchdog (#1052).

Publishes a heartbeat payload every 60 seconds via NATS and registers
a Home Assistant binary_sensor via NATS auto-discovery on startup.
The nats-mqtt-bridge forwards ha.discovery.* to MQTT homeassistant/...
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.heartbeat")

NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

INTERVAL_SECONDS = 60
VERSION = "1.0"


class HeartbeatPublisher:
    """Publishes HEMS heartbeat to NATS for HA watchdog monitoring.

    Publishes on two subjects every tick:
      - heartbeat.hems          — JSON payload with timestamp/status/version
      - ha.discovery.binary_sensor.hems_heartbeat.config — HA discovery on startup
    """

    def __init__(self) -> None:
        self._nats: NatsPublisher = NatsPublisher(url=NATS_URL)

    async def _publish_discovery(self) -> None:
        """Publish HA binary_sensor auto-discovery via NATS."""
        config = {
            "name": "HEMS Heartbeat",
            "device_class": "connectivity",
            "state_topic": "homelab/hems/heartbeat/state",
            "unique_id": "hems_heartbeat",
        }
        await self._nats.publish(
            "ha.discovery.binary_sensor.hems_heartbeat.config", config
        )
        logger.info("Published HA auto-discovery for hems_heartbeat binary_sensor")

    async def _publish_tick(self) -> None:
        """Publish one heartbeat tick."""
        ts = datetime.now(timezone.utc).isoformat()
        await self._nats.publish(
            "heartbeat.hems",
            {"timestamp": ts, "status": "ok", "version": VERSION},
        )
        logger.debug("Heartbeat published at %s", ts)

    async def run_forever(self) -> None:
        """Connect, publish discovery, then tick every INTERVAL_SECONDS."""
        await self._nats.connect()
        await self._publish_discovery()

        try:
            while True:
                await self._publish_tick()
                await asyncio.sleep(INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("HeartbeatPublisher shutting down")
        finally:
            await self._nats.close()
