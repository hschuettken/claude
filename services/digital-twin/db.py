"""PostgreSQL connection pool and schema migration for Digital Twin."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import asyncpg

    _ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None  # type: ignore[assignment]
    _ASYNCPG_AVAILABLE = False


_pool: Optional[object] = None


async def init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    if not _ASYNCPG_AVAILABLE:
        logger.warning("asyncpg not installed — DB features disabled")
        return
    try:
        _pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        logger.info("db pool connected dsn=%s", dsn.split("@")[-1])
        await _run_migrations()
    except Exception as exc:
        logger.warning("db pool init failed: %s — DB features disabled", exc)
        _pool = None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()  # type: ignore[union-attr]
        except Exception:
            pass
        _pool = None


def get_pool():
    return _pool


async def fetchrow(query: str, *args):
    if _pool is None:
        return None
    async with _pool.acquire() as conn:  # type: ignore[union-attr]
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args) -> list:
    if _pool is None:
        return []
    async with _pool.acquire() as conn:  # type: ignore[union-attr]
        return await conn.fetch(query, *args)


async def execute(query: str, *args) -> str:
    if _pool is None:
        return "SKIPPED"
    async with _pool.acquire() as conn:  # type: ignore[union-attr]
        return await conn.execute(query, *args)


async def _run_migrations() -> None:
    """Apply schema migrations idempotently."""
    migration_files = [
        _MIGRATION_001_ROOMS,
        _MIGRATION_002_STATE_SNAPSHOTS,
        _MIGRATION_003_SIMULATION_RESULTS,
    ]
    for migration in migration_files:
        try:
            await execute(migration)
        except Exception as exc:
            logger.error("migration_failed: %s", exc)
            raise


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_MIGRATION_001_ROOMS = """
CREATE TABLE IF NOT EXISTS dt_rooms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id         TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    floor           TEXT,
    area_m2         DOUBLE PRECISION,
    ha_temperature_entity  TEXT,
    ha_humidity_entity     TEXT,
    ha_occupancy_entity    TEXT,
    ha_heating_entity      TEXT,
    extra_entities  JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dt_rooms_room_id_idx ON dt_rooms (room_id);
"""

_MIGRATION_002_STATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS dt_state_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    energy_state    JSONB NOT NULL DEFAULT '{}'::jsonb,
    room_states     JSONB NOT NULL DEFAULT '{}'::jsonb,
    safe_mode       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS dt_state_snapshots_captured_at_idx
    ON dt_state_snapshots (captured_at DESC);
"""

_MIGRATION_003_SIMULATION_RESULTS = """
CREATE TABLE IF NOT EXISTS dt_simulation_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    horizon_hours   INTEGER NOT NULL,
    report          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS dt_simulation_results_created_at_idx
    ON dt_simulation_results (created_at DESC);
"""
