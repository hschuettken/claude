"""Decision audit logger — InfluxDB + Postgres (#1039).

Provides log_decision() for logging HEMS control decisions.

hems.decisions schema (migration 003):
    id, timestamp, mode, flow_temp_setpoint, reason, pv_available_w,
    outdoor_temp_c, created_at
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("hems.decision_logger")

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)


async def log_decision(
    room: str,
    action: str,
    reason: str,
    setpoint: float,
    actual_temp: float,
    confidence: float,
    mode: str = "auto",
    pv_available_w: Optional[float] = None,
    outdoor_temp_c: Optional[float] = None,
) -> None:
    """Log a HEMS control decision to InfluxDB and Postgres.

    Both writes are best-effort — failures are logged but never raised.

    Args:
        room:          Room identifier (e.g. 'wohnzimmer').
        action:        Action taken (e.g. 'setpoint_change', 'mode_switch').
        reason:        Textual reason for the decision.
        setpoint:      Target temperature setpoint (°C).
        actual_temp:   Measured room temperature at decision time (°C).
        confidence:    Decision confidence (0.0–1.0).
        mode:          HEMS mode string ('comfort', 'eco', 'off', 'dhw', 'auto').
        pv_available_w: Available PV power at decision time (W), if known.
        outdoor_temp_c: Outdoor temperature at decision time (°C), if known.
    """
    # InfluxDB (best-effort)
    try:
        from influxdb_setup import write_hems_point

        fields: dict = {
            "setpoint": float(setpoint),
            "actual_temp": float(actual_temp),
            "confidence": float(confidence),
        }
        if pv_available_w is not None:
            fields["pv_available_w"] = float(pv_available_w)
        if outdoor_temp_c is not None:
            fields["outdoor_temp_c"] = float(outdoor_temp_c)

        await write_hems_point(
            measurement="hems_decisions",
            fields=fields,
            tags={
                "room": room,
                "action": action,
                "mode": mode,
            },
        )
    except Exception as e:
        logger.warning("InfluxDB hems_decisions write failed: %s", e)

    # Postgres (best-effort)
    # Maps onto hems.decisions schema:
    #   mode              → mode
    #   flow_temp_setpoint → setpoint
    #   reason            → "{action}: {reason}"
    #   pv_available_w    → pv_available_w (if provided)
    #   outdoor_temp_c    → outdoor_temp_c (if provided)
    try:
        import asyncpg

        pg_url = DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        conn = await asyncpg.connect(pg_url)
        try:
            full_reason = f"[{room}] {action}: {reason}"
            await conn.execute(
                """
                INSERT INTO hems.decisions
                    (mode, flow_temp_setpoint, reason, pv_available_w, outdoor_temp_c)
                VALUES ($1, $2, $3, $4, $5)
                """,
                mode,
                float(setpoint),
                full_reason,
                float(pv_available_w) if pv_available_w is not None else None,
                float(outdoor_temp_c) if outdoor_temp_c is not None else None,
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Postgres hems.decisions write failed: %s", e)
