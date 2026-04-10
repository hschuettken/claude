"""Log NN training runs to InfluxDB and Postgres (#1034).

Each training epoch is written to:
  - InfluxDB measurement ``nn_training_log`` (via influxdb_setup.write_hems_point)
  - hems.nn_training_log Postgres table (migration 007)

Usage:
    from nn_training_log import log_training_run
    await log_training_run("thermal_lstm", epoch=5, loss=0.0134, val_loss=0.0156,
                           duration_seconds=42.7, samples_used=8640)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://homelab:homelab@192.168.0.80:5432/homelab"
)


def _clean_url(url: str) -> str:
    """Strip SQLAlchemy driver prefixes so asyncpg can connect."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


async def log_training_run(
    model_type: str,
    epoch: int,
    loss: float,
    val_loss: Optional[float] = None,
    duration_seconds: float = 0.0,
    samples_used: int = 0,
    notes: str = "",
) -> None:
    """Write training run metrics to InfluxDB and Postgres (#1034).

    Both writes are best-effort: a failure in one does not block the other.

    Args:
        model_type: Logical model type tag (e.g. "thermal_lstm").
        epoch: Training epoch number (1-based).
        loss: Training loss for this epoch.
        val_loss: Validation loss, if available.
        duration_seconds: Wall-clock seconds spent on this epoch.
        samples_used: Number of training samples used.
        notes: Free-text annotation (hyperparams, flags, etc.).
    """
    # ---- InfluxDB -------------------------------------------------------
    try:
        from influxdb_setup import write_hems_point

        fields: dict = {
            "epoch": epoch,
            "loss": round(loss, 6),
            "duration_seconds": round(duration_seconds, 2),
            "samples_used": samples_used,
        }
        if val_loss is not None:
            fields["val_loss"] = round(val_loss, 6)
        if notes:
            fields["notes"] = notes

        await write_hems_point(
            "nn_training_log",
            fields,
            tags={"model_type": model_type},
        )
    except Exception as e:
        logger.warning("Failed to log training run to InfluxDB: %s", e)

    # ---- Postgres -------------------------------------------------------
    try:
        import asyncpg

        conn = await asyncpg.connect(_clean_url(DB_URL))
        try:
            await conn.execute(
                """
                INSERT INTO hems.nn_training_log
                    (model_type, epoch, loss, val_loss,
                     duration_seconds, samples_used, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                model_type,
                epoch,
                loss,
                val_loss,
                duration_seconds,
                samples_used,
                notes,
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Failed to persist training log to Postgres: %s", e)
