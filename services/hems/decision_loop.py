"""HEMS decision loop (#1048).

Polls room temperatures from Home Assistant, compares against schedule
setpoints, and publishes MQTT commands when the delta exceeds 0.5 °C.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from dry_run import gate_actuation
from schedule_manager import ScheduleManager
from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.decision_loop")

HA_URL = os.getenv("HA_URL", "http://192.168.0.40:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")
DELTA_THRESHOLD = 0.5  # °C

# Module-level NATS publisher
_nats: NatsPublisher | None = None


def _get_nats() -> NatsPublisher:
    global _nats
    if _nats is None:
        _nats = NatsPublisher(url=NATS_URL)
    return _nats


# Optional import — decision_logger may not yet exist
try:
    from decision_logger import log_decision  # type: ignore[import-not-found]

    _log_decision_available = True
except ImportError:
    _log_decision_available = False

    async def log_decision(*args, **kwargs) -> None:  # type: ignore[misc]
        pass


class HEMSDecisionLoop:
    """Periodic decision loop: read temps → compare setpoints → command."""

    def __init__(self, interval_s: int = 300) -> None:
        self.interval_s: int = int(
            os.getenv("HEMS_DECISION_INTERVAL_S", str(interval_s))
        )
        self._schedule: ScheduleManager = ScheduleManager()
        self._room_entities: list[str] = self._parse_room_entities()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_room_entities() -> list[str]:
        raw = os.getenv("HEMS_ROOM_ENTITIES", "")
        return [e.strip() for e in raw.split(",") if e.strip()]

    # ------------------------------------------------------------------
    # HA helpers
    # ------------------------------------------------------------------

    async def _get_temperature(self, entity_id: str) -> Optional[float]:
        """Fetch current temperature state for an entity from HA."""
        url = f"{HA_URL}/api/states/{entity_id}"
        headers = {"Authorization": f"Bearer {HA_TOKEN}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                state = resp.json().get("state")
                return float(state)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Failed to fetch temperature for %s: %s", entity_id, exc)
            return None

    # ------------------------------------------------------------------
    # NATS helpers
    # ------------------------------------------------------------------

    async def _publish_command(self, room: str, setpoint: float) -> None:
        """Publish a heating command for a room via NATS."""
        subject = f"energy.hems.commands.{room}"
        payload = {
            "room": room,
            "setpoint": setpoint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        pub = _get_nats()
        if not pub.connected:
            await pub.connect()
        await pub.publish(subject, payload)
        logger.info(
            "Published heating command for room=%s setpoint=%.1f", room, setpoint
        )

    # ------------------------------------------------------------------
    # Per-room decision
    # ------------------------------------------------------------------

    async def _decide_for_room(self, entity_id: str) -> None:
        """Run one decision cycle for a single room entity."""
        current_temp = await self._get_temperature(entity_id)
        if current_temp is None:
            return

        setpoint = self._schedule.get_setpoint()
        delta = setpoint - current_temp

        logger.debug(
            "Room %s: current=%.2f setpoint=%.2f delta=%.2f",
            entity_id,
            current_temp,
            setpoint,
            delta,
        )

        # Strip domain prefix for MQTT topic (sensor.living_room → living_room)
        room = entity_id.split(".")[-1]

        if abs(delta) > DELTA_THRESHOLD:
            action_name = f"heat_command:{room}:setpoint={setpoint:.1f}"
            if gate_actuation(action_name):
                await self._publish_command(room, setpoint)

            if _log_decision_available:
                action = (
                    "setpoint_command" if abs(delta) > DELTA_THRESHOLD else "no_action"
                )
                await log_decision(
                    room=room,
                    action=action,
                    reason=f"delta={delta:.2f}C threshold={DELTA_THRESHOLD}C",
                    setpoint=setpoint,
                    actual_temp=current_temp,
                    confidence=1.0,
                )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Run the decision loop indefinitely, one cycle per interval_s."""
        logger.info(
            "HEMSDecisionLoop starting: interval=%ds rooms=%s",
            self.interval_s,
            self._room_entities,
        )

        while True:
            if not self._room_entities:
                logger.warning("HEMS_ROOM_ENTITIES is empty — no rooms to evaluate")
            else:
                for entity_id in self._room_entities:
                    try:
                        await self._decide_for_room(entity_id)
                    except Exception as exc:
                        logger.error(
                            "Unhandled error for room %s: %s",
                            entity_id,
                            exc,
                            exc_info=True,
                        )

            await asyncio.sleep(self.interval_s)
