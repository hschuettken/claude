"""Database connection and session management."""

import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Get database URL from environment
DATABASE_URL = os.getenv(
    "MARKETING_DB_URL",
    "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab",
)

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency to get async database session."""
    async with async_session_maker() as session:
        yield session
