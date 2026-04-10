"""HEMS heartbeat publisher for HA watchdog (#1052).

Publishes a heartbeat payload every 60 seconds via MQTT and registers
a Home Assistant binary_sensor via MQTT auto-discovery on startup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from functools import partial
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger("hems.heartbeat")

MQTT_BROKER = os.getenv("MQTT_HOST", "192.168.0.73")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

HEARTBEAT_TOPIC = "homelab/hems/heartbeat"
HEARTBEAT_STATE_TOPIC = "homelab/hems/heartbeat/state"
HA_DISCOVERY_TOPIC = "homeassistant/binary_sensor/hems_heartbeat/config"

INTERVAL_SECONDS = 60
VERSION = "1.0"


class HeartbeatPublisher:
    """Publishes HEMS heartbeat to MQTT for HA watchdog monitoring.

    Publishes on two topics every tick:
      - homelab/hems/heartbeat        — JSON payload with timestamp/status/version
      - homelab/hems/heartbeat/state  — plain "ON" string for HA binary_sensor
    """

    def __init__(self) -> None:
        self._client: Optional[mqtt.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Internal sync helpers (run in executor to avoid blocking the loop)
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        client = mqtt.Client(client_id="hems-heartbeat", clean_session=True)
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=90)
        client.loop_start()
        self._client = client
        logger.info("MQTT heartbeat client connected to %s:%s", MQTT_BROKER, MQTT_PORT)

    def _publish_discovery(self) -> None:
        if self._client is None:
            return
        config = {
            "name": "HEMS Heartbeat",
            "device_class": "connectivity",
            "state_topic": HEARTBEAT_STATE_TOPIC,
            "unique_id": "hems_heartbeat",
        }
        self._client.publish(HA_DISCOVERY_TOPIC, json.dumps(config), retain=True)
        logger.info("Published HA auto-discovery for hems_heartbeat binary_sensor")

    def _publish_tick(self) -> None:
        if self._client is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        payload = json.dumps({"timestamp": ts, "status": "ok", "version": VERSION})
        self._client.publish(HEARTBEAT_TOPIC, payload)
        self._client.publish(HEARTBEAT_STATE_TOPIC, "ON")
        logger.debug("Heartbeat published at %s", ts)

    def _disconnect(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    # ------------------------------------------------------------------
    # Async public interface
    # ------------------------------------------------------------------

    async def _run_in_executor(self, fn: partial) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, fn)

    async def run_forever(self) -> None:
        """Connect, publish discovery, then tick every INTERVAL_SECONDS."""
        await self._run_in_executor(partial(self._connect))
        await self._run_in_executor(partial(self._publish_discovery))

        try:
            while True:
                await self._run_in_executor(partial(self._publish_tick))
                await asyncio.sleep(INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("HeartbeatPublisher shutting down")
        finally:
            await self._run_in_executor(partial(self._disconnect))
