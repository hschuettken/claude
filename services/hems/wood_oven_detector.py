"""Wood oven active state detector (Task #1099).

Detects active wood oven from room temperature and CO sensor data.
Publishes MQTT events on state transitions.

Usage:
    detector = WoodOvenDetector()
    active, reason = await detector.is_oven_active()
    status = await detector.get_status()
    await detector.run_detection_loop()
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.wood_oven_detector")

# Environment configuration
HA_URL = os.getenv("HA_URL", "http://192.168.0.40:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_TEMP_SENSOR = os.getenv("HEMS_OVEN_TEMP_SENSOR", "sensor.wohnzimmer_temperature")
HA_CO_SENSOR = os.getenv("HEMS_OVEN_CO_SENSOR", "sensor.wohnzimmer_co2")
OVEN_TEMP_THRESHOLD = float(os.getenv("HEMS_OVEN_TEMP_THRESHOLD", "24.0"))
OVEN_RAPID_RISE_K_PER_MIN = float(os.getenv("HEMS_OVEN_RISE_RATE", "0.3"))
NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

# Module-level NATS publisher
_nats: NatsPublisher | None = None


def _get_nats() -> NatsPublisher:
    global _nats
    if _nats is None:
        _nats = NatsPublisher(url=NATS_URL)
    return _nats


class WoodOvenDetector:
    """Detects active wood oven from temperature and CO sensors."""

    def __init__(self) -> None:
        """Initialize detector with configuration from environment."""
        self._oven_active: bool = False
        self._last_temp: Optional[float] = None
        self._last_temp_time: Optional[float] = None

    async def _get_ha_state(self, entity_id: str) -> Optional[float]:
        """Fetch numeric state from Home Assistant.

        Args:
            entity_id: HA entity ID (e.g., "sensor.wohnzimmer_temperature")

        Returns:
            Numeric state or None if failed/unavailable.
        """
        url = f"{HA_URL}/api/states/{entity_id}"
        headers = {"Authorization": f"Bearer {HA_TOKEN}"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                state = data.get("state")
                if state and state.lower() != "unavailable":
                    return float(state)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Failed to fetch %s: %s", entity_id, exc)
        return None

    async def is_oven_active(self) -> tuple[bool, str]:
        """Detect if wood oven is currently active.

        Returns:
            Tuple of (is_active, reason_string).
            Reasons: "room_temp_above_threshold", "high_co2_detected", "inactive".
        """
        room_temp = await self._get_ha_state(HA_TEMP_SENSOR)
        if room_temp is None:
            logger.warning("Could not read room temperature sensor")
            return False, "sensor_unavailable"

        # Check primary threshold: room temp above baseline
        if room_temp > OVEN_TEMP_THRESHOLD:
            return True, "room_temp_above_threshold"

        # Check secondary indicator: CO2 sensor if available
        co_ppm = await self._get_ha_state(HA_CO_SENSOR)
        if co_ppm is not None and co_ppm > 800:
            return True, "high_co2_detected"

        return False, "inactive"

    async def get_status(self) -> dict:
        """Get full detector status including confidence.

        Returns:
            Dict with keys: active, confidence, reason, room_temp, co_ppm.
        """
        room_temp = await self._get_ha_state(HA_TEMP_SENSOR)
        co_ppm = await self._get_ha_state(HA_CO_SENSOR)
        is_active, reason = await self.is_oven_active()

        # Compute confidence
        confidence = 0.0
        if is_active:
            if reason == "room_temp_above_threshold" and room_temp is not None:
                # Confidence scales with how far above threshold
                confidence = min(1.0, (room_temp - OVEN_TEMP_THRESHOLD) / 5.0)
            elif reason == "high_co2_detected" and co_ppm is not None:
                confidence = min(1.0, co_ppm / 1000.0)
        else:
            confidence = 1.0 if room_temp is not None else 0.5

        return {
            "active": is_active,
            "confidence": confidence,
            "reason": reason,
            "room_temp": room_temp,
            "co_ppm": co_ppm,
        }

    async def _publish_nats(self, payload: dict) -> None:
        """Publish wood oven state change to NATS.

        Args:
            payload: Dict with at least "active" and "timestamp" keys.
        """
        subject = "energy.hems.wood_oven"
        try:
            pub = _get_nats()
            if not pub.connected:
                await pub.connect()
            await pub.publish(subject, payload)
            logger.info("Published wood oven state: active=%s", payload["active"])
        except Exception as exc:
            logger.error("Failed to publish to NATS: %s", exc)

    async def run_detection_loop(self, interval_s: int = 300) -> None:
        """Run detection loop, publishing state changes.

        Runs every `interval_s` seconds. On transition from inactive→active
        or active→inactive, publishes to MQTT.

        Args:
            interval_s: Check interval in seconds (default 300 = 5 min).
        """
        logger.info("Wood oven detector loop starting: interval=%ds", interval_s)

        while True:
            try:
                is_active, reason = await self.is_oven_active()

                # State transition: inactive → active
                if is_active and not self._oven_active:
                    self._oven_active = True
                    await self._publish_nats(
                        {
                            "active": True,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "reason": reason,
                        }
                    )
                    logger.info("Wood oven detected as ACTIVE (%s)", reason)

                # State transition: active → inactive
                elif not is_active and self._oven_active:
                    self._oven_active = False
                    await self._publish_nats(
                        {
                            "active": False,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "reason": reason,
                        }
                    )
                    logger.info("Wood oven detected as INACTIVE")

            except Exception as exc:
                logger.error(
                    "Unhandled error in detection loop: %s", exc, exc_info=True
                )

            await asyncio.sleep(interval_s)
