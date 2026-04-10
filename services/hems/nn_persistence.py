"""NN model weight persistence to Postgres hems.nn_models (#1033).

Stores serialized PyTorch state_dicts in the weights_blob BYTEA column.
The hems.nn_models table was created by migration 003; migration 007 adds
the weights_blob, model_version, and metrics columns needed here.

Usage:
    from nn_persistence import save_model_weights, load_latest_weights
    model_id = await save_model_weights(model, "thermal_lstm", "1.2.0")
    ok = await load_latest_weights(model, "thermal_lstm")
"""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Optional

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://homelab:homelab@192.168.0.80:5432/homelab"
)


def _clean_url(url: str) -> str:
    """Strip SQLAlchemy driver prefixes so asyncpg can connect."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


async def save_model_weights(
    model: nn.Module,
    model_type: str,
    model_version: str,
    metrics: Optional[dict] = None,
    set_active: bool = True,
) -> Optional[int]:
    """Serialize model weights to Postgres BYTEA (#1033).

    Args:
        model: PyTorch module whose state_dict will be serialized.
        model_type: Logical model type tag (e.g. "thermal_lstm", "pinn").
        model_version: Semantic version string (e.g. "1.2.0").
        metrics: Optional dict of evaluation metrics (mae, mse, …).
        set_active: If True, deactivate all prior entries for this
                    model_type before inserting the new one.

    Returns:
        The new row's ``id``, or None on failure.
    """
    try:
        import asyncpg

        buf = io.BytesIO()
        torch.save(model.state_dict(), buf)
        weights_bytes = buf.getvalue()

        conn = await asyncpg.connect(_clean_url(DB_URL))
        try:
            if set_active:
                await conn.execute(
                    "UPDATE hems.nn_models SET is_active = FALSE WHERE model_type = $1",
                    model_type,
                )

            row = await conn.fetchrow(
                """
                INSERT INTO hems.nn_models
                    (model_version, model_type, weights_blob, metrics, is_active)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                model_version,
                model_type,
                weights_bytes,
                json.dumps(metrics or {}),
                set_active,
            )
        finally:
            await conn.close()

        logger.info(
            "Saved %s weights (version=%s) → hems.nn_models id=%s",
            model_type,
            model_version,
            row["id"],
        )
        return row["id"]

    except Exception as e:
        logger.error("Failed to save model weights: %s", e)
        return None


async def load_latest_weights(model: nn.Module, model_type: str) -> bool:
    """Load most recent active weights from Postgres into model (#1033).

    Args:
        model: PyTorch module to load weights into (in-place).
        model_type: Logical model type tag to query.

    Returns:
        True if weights were found and loaded, False otherwise.
    """
    try:
        import asyncpg

        conn = await asyncpg.connect(_clean_url(DB_URL))
        try:
            row = await conn.fetchrow(
                """
                SELECT weights_blob
                FROM hems.nn_models
                WHERE model_type = $1
                  AND is_active = TRUE
                  AND weights_blob IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                model_type,
            )
        finally:
            await conn.close()

        if row and row["weights_blob"]:
            buf = io.BytesIO(bytes(row["weights_blob"]))
            state = torch.load(buf, map_location="cpu")
            model.load_state_dict(state)
            logger.info("Loaded weights for model_type=%s from Postgres", model_type)
            return True

        logger.warning("No active weights found for model_type=%s", model_type)
        return False

    except Exception as e:
        logger.error("Failed to load model weights: %s", e)
        return False
