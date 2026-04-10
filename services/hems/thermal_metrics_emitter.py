"""Thermal metrics emitter — writes thermal_training points every 5 minutes (#1036).

Reads room temperatures from HA REST API and writes to InfluxDB
measurement ``thermal_training`` for model training purposes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("hems.thermal_metrics_emitter")

HA_URL = os.getenv("HA_URL", "http://192.168.0.40:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
EMIT_INTERVAL_S = 300  # 5 minutes


class ThermalMetricsEmitter:
    """Reads HA room temperatures and writes to InfluxDB every 5 minutes."""

    def __init__(self, schedule_manager=None):
        """
        Args:
            schedule_manager: Optional schedule manager instance with
                              ``get_current_setpoint(room_id)`` method.
                              Used to populate the setpoint field.
        """
        self._schedule_manager = schedule_manager

    def _get_room_entities(self) -> list[str]:
        """Return room entity IDs from env var HEMS_ROOM_ENTITIES."""
        raw = os.getenv("HEMS_ROOM_ENTITIES", "")
        return [e.strip() for e in raw.split(",") if e.strip()]

    async def _fetch_ha_state(self, entity_id: str) -> Optional[float]:
        """Fetch numeric state for a HA entity via REST API.

        Returns the float state value, or None on error / non-numeric state.
        """
        try:
            import httpx

            url = f"{HA_URL}/api/states/{entity_id}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {HA_TOKEN}",
                        "Content-Type": "application/json",
                    },
                )
                if r.status_code != 200:
                    logger.warning(
                        "HA state fetch failed for %s: HTTP %s",
                        entity_id,
                        r.status_code,
                    )
                    return None
                data = r.json()
                return float(data["state"])
        except (ValueError, KeyError, TypeError):
            logger.warning("Non-numeric state for entity %s", entity_id)
            return None
        except Exception as e:
            logger.warning("Error fetching HA state for %s: %s", entity_id, e)
            return None

    def _get_setpoint(self, room: str) -> float:
        """Return setpoint for a room from schedule manager, or 20.0 as fallback."""
        if self._schedule_manager is None:
            return 20.0
        try:
            sp = self._schedule_manager.get_current_setpoint(room)
            if sp is not None:
                return float(sp)
        except Exception:
            pass
        return 20.0

    async def emit_once(self) -> None:
        """Emit one round of thermal_training points for all configured rooms."""
        from influxdb_setup import write_hems_point

        entities = self._get_room_entities()
        if not entities:
            logger.debug("No room entities configured (HEMS_ROOM_ENTITIES is empty)")
            return

        for entity_id in entities:
            temperature = await self._fetch_ha_state(entity_id)
            if temperature is None:
                continue

            # Strip domain prefix for the tag value
            room = entity_id.removeprefix("sensor.")

            setpoint = self._get_setpoint(room)

            try:
                await write_hems_point(
                    measurement="thermal_training",
                    fields={
                        "temperature": temperature,
                        "setpoint": setpoint,
                    },
                    tags={"room": room},
                )
                logger.debug(
                    "thermal_training written: room=%s temp=%.2f setpoint=%.2f",
                    room,
                    temperature,
                    setpoint,
                )
            except Exception as e:
                logger.error("Failed to write thermal_training for %s: %s", room, e)

    async def run_loop(self) -> None:
        """Run the emission loop indefinitely, emitting every 5 minutes."""
        logger.info("ThermalMetricsEmitter starting (interval=%ds)", EMIT_INTERVAL_S)
        while True:
            try:
                await self.emit_once()
            except Exception as e:
                logger.error("Unexpected error in ThermalMetricsEmitter loop: %s", e)
            await asyncio.sleep(EMIT_INTERVAL_S)
