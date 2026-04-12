"""asyncpg connection pool for companion module."""

from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool(settings) -> asyncpg.Pool:
    """Return (or create) the global asyncpg connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.postgres_url, min_size=2, max_size=10
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
