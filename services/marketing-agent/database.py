"""Database connection and session management."""
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from typing import Optional

_engine = None
_session_maker = None

def _get_engine():
    global _engine, _session_maker
    if _engine is None:
        db_url = os.getenv(
            "MARKETING_DB_URL",
            "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab",
        )
        # Ensure asyncpg dialect
        if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
        _engine = create_async_engine(db_url, echo=False, pool_size=10, max_overflow=20)
        _session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine, _session_maker

async def get_db() -> AsyncSession:
    """Dependency to get async database session."""
    _, session_maker = _get_engine()
    async with session_maker() as session:
        yield session
