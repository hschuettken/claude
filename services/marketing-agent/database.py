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


# Sync SessionLocal for backward compatibility (used by app/consumers/*.py)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker as sync_sessionmaker
import os

def _get_sync_engine():
    """Get synchronous SQLAlchemy engine."""
    db_url = os.getenv("MARKETING_DB_URL", "postgresql://homelab:homelab@192.168.0.80:5432/homelab")
    # Convert asyncpg URL to sync psycopg2-compatible URL
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("asyncpg://", "postgresql://")
    return create_engine(sync_url)

_sync_engine = None
_SessionLocal = None

def _get_session_local():
    global _sync_engine, _SessionLocal
    if _SessionLocal is None:
        _sync_engine = _get_sync_engine()
        _SessionLocal = sync_sessionmaker(bind=_sync_engine, autocommit=False, autoflush=False)
    return _SessionLocal

class SessionLocal:
    """Sync session factory proxy for backward compatibility."""
    def __new__(cls):
        return _get_session_local()()
