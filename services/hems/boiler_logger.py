"""Boiler state logger — InfluxDB + Postgres (#1038).

Writes boiler telemetry to both stores on every log call.
The run_loop() method polls HA sensors every 60 seconds.

hems.boiler_state schema (migration 006):
    ts, burner_on, flow_temp, return_temp, dhw_active, mode, energy_wh
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("hems.boiler_logger")

HA_URL = os.getenv("HA_URL", "http://192.168.0.40:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)
POLL_INTERVAL_S = 60

# HA entity IDs — override via env if different in the installation
HA_ENTITY_FLOW_TEMP = os.getenv("HEMS_HA_FLOW_TEMP", "sensor.boiler_flow_temp")
HA_ENTITY_RETURN_TEMP = os.getenv("HEMS_HA_RETURN_TEMP", "sensor.boiler_return_temp")
HA_ENTITY_BURNER_ON = os.getenv("HEMS_HA_BURNER_ON", "binary_sensor.boiler_burner")
HA_ENTITY_MODE = os.getenv("HEMS_HA_BOILER_MODE", "sensor.boiler_mode")

# Estimated burner power when active (kW)
BURNER_POWER_KW = 24.0


class BoilerStateLogger:
    """Logs boiler state to InfluxDB and Postgres."""

    async def _fetch_ha_state(self, entity_id: str) -> Optional[str]:
        """Fetch raw HA entity state string."""
        try:
            import httpx

            url = f"{HA_URL}/api/states/{entity_id}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {HA_TOKEN}"},
                )
                if r.status_code != 200:
                    logger.warning(
                        "HA fetch failed for %s: HTTP %s", entity_id, r.status_code
                    )
                    return None
                return r.json().get("state")
        except Exception as e:
            logger.warning("Error fetching HA state %s: %s", entity_id, e)
            return None

    async def log_state(
        self,
        boiler_temp: float,
        flow_temp: float,
        return_temp: float,
        burner_on: bool,
        mode: str,
    ) -> None:
        """Write boiler state to InfluxDB and Postgres.

        Args:
            boiler_temp: Current boiler temperature (°C) — stored in InfluxDB only
                         (schema has no boiler_temp column, only flow/return).
            flow_temp:   Flow temperature (°C).
            return_temp: Return temperature (°C).
            burner_on:   Whether burner is active.
            mode:        Operational mode string ('comfort', 'eco', 'off', 'dhw').
        """
        power_kw = BURNER_POWER_KW if burner_on else 0.0

        # InfluxDB write (best-effort)
        try:
            from influxdb_setup import write_hems_point

            await write_hems_point(
                measurement="boiler_state",
                fields={
                    "boiler_temp": float(boiler_temp),
                    "flow_temp": float(flow_temp),
                    "return_temp": float(return_temp),
                    "burner_on": int(burner_on),
                    "power_kw": power_kw,
                },
                tags={"mode": mode},
            )
        except Exception as e:
            logger.warning("InfluxDB boiler_state write failed: %s", e)

        # Postgres write (best-effort)
        try:
            import asyncpg

            pg_url = DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
                "postgresql+psycopg2://", "postgresql://"
            )
            conn = await asyncpg.connect(pg_url)
            try:
                # Schema columns: ts, burner_on, flow_temp, return_temp, dhw_active, mode, energy_wh
                # dhw_active derived from mode; energy_wh not available here (left NULL)
                dhw_active = mode == "dhw"
                await conn.execute(
                    """
                    INSERT INTO hems.boiler_state
                        (burner_on, flow_temp, return_temp, dhw_active, mode)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    burner_on,
                    float(flow_temp),
                    float(return_temp),
                    dhw_active,
                    mode,
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Postgres boiler_state write failed: %s", e)

    async def run_loop(self) -> None:
        """Poll HA sensors every 60 seconds and log boiler state."""
        logger.info("BoilerStateLogger starting (interval=%ds)", POLL_INTERVAL_S)
        while True:
            try:
                flow_str = await self._fetch_ha_state(HA_ENTITY_FLOW_TEMP)
                return_str = await self._fetch_ha_state(HA_ENTITY_RETURN_TEMP)
                burner_str = await self._fetch_ha_state(HA_ENTITY_BURNER_ON)
                mode_str = await self._fetch_ha_state(HA_ENTITY_MODE)

                flow_temp = (
                    float(flow_str)
                    if flow_str not in (None, "unavailable", "unknown")
                    else 0.0
                )
                return_temp = (
                    float(return_str)
                    if return_str not in (None, "unavailable", "unknown")
                    else 0.0
                )
                # binary_sensor: "on"/"off"
                burner_on = burner_str == "on" if burner_str is not None else False
                mode = (
                    mode_str
                    if mode_str not in (None, "unavailable", "unknown")
                    else "unknown"
                )

                # boiler_temp not in schema — pass flow_temp as proxy
                await self.log_state(
                    boiler_temp=flow_temp,
                    flow_temp=flow_temp,
                    return_temp=return_temp,
                    burner_on=burner_on,
                    mode=mode,
                )
            except Exception as e:
                logger.error("Unexpected error in BoilerStateLogger loop: %s", e)

            await asyncio.sleep(POLL_INTERVAL_S)
