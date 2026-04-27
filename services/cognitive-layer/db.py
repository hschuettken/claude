"""Async PostgreSQL connection pool — graceful no-op when DB unavailable."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import asyncpg  # type: ignore
    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False

DATABASE_URL: Optional[str] = os.getenv(
    "COGNITIVE_DB_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)

_pool: Optional[Any] = None


async def init_pool() -> None:
    global _pool
    if not _ASYNCPG_AVAILABLE:
        logger.warning("asyncpg not installed — running without persistent storage")
        return
    if not DATABASE_URL:
        logger.info("COGNITIVE_DB_URL not set — running without persistent storage")
        return
    try:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        logger.info("cognitive_layer db_pool_created dsn=%s", DATABASE_URL.split("@")[-1])
        await _run_migrations()
    except Exception as exc:
        logger.error("cognitive_layer db_pool_failed error=%s", exc)
        _pool = None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Optional[Any]:
    return _pool


async def execute(query: str, *args: Any) -> None:
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(query, *args)


async def fetchrow(query: str, *args: Any) -> Optional[Any]:
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args: Any) -> list:
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchval(query: str, *args: Any) -> Optional[Any]:
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def _run_migrations() -> None:
    """Run SQL migrations in order if tables don't exist yet."""
    import pathlib
    migrations_dir = pathlib.Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        return
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        try:
            sql = sql_file.read_text()
            async with _pool.acquire() as conn:
                await conn.execute(sql)
            logger.info("cognitive_layer migration_applied file=%s", sql_file.name)
        except Exception as exc:
            logger.warning("cognitive_layer migration_skipped file=%s error=%s", sql_file.name, exc)
