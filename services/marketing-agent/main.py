"""
Marketing Agent Service — FastAPI backend for content drafting and Ghost CMS integration.

Provides:
- Marketing signals/opportunities API
- Content draft management
- Ghost CMS publishing pipeline
- Content pillar and voice rule management
- Analytics integration (future)

Environment variables:
  - MARKETING_DB_URL: PostgreSQL connection string
  - GHOST_ADMIN_API_KEY: Ghost API key (format: id:secret_hex)
  - GHOST_URL: Ghost base URL (default: https://layer8.schuettken.net)
  - MARKETING_PORT: API port (default: 8210)
"""
import os
import logging
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_sessionmaker,
)
from fastapi import FastAPI, Depends, status
from fastapi.responses import JSONResponse

from models import Base
from api import signals_router, topics_router, drafts_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# Database configuration
DATABASE_URL = os.getenv(
    "MARKETING_DB_URL",
    "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab",
)

# Create async engine and session factory
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency injection for database session."""
    async with async_session_maker() as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    logger.info("Starting Marketing Agent service...")
    
    # Startup: Create tables
    async with engine.begin() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS marketing")
        await conn.commit()
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database tables created/verified")
    
    # Initialize Task 338: High-relevance signal consumer (NATS automation)
    if os.getenv("NATS_URL") or os.getenv("nats_url"):
        logger.info("Initializing Task 338: NATS high-relevance signal consumer...")
        try:
            from app.consumers import start_consumers
            await start_consumers()
            logger.info("✅ Task 338: High-relevance signal consumer started successfully")
        except ImportError:
            logger.warning("Task 338: Consumer module not found, NATS automation disabled")
        except Exception as e:
            logger.warning(f"Task 338: Failed to start high-relevance signal consumer: {e}")
    else:
        logger.info("NATS_URL not configured, Task 338 NATS automation disabled")
    
    yield
    
    # Shutdown: Close consumers
    logger.info("Shutting down Task 338 consumers...")
    try:
        from app.consumers import close_consumers
        await close_consumers()
        logger.info("Task 338 consumers stopped")
    except Exception as e:
        logger.warning(f"Error stopping Task 338 consumers: {e}")
    
    # Shutdown: Close engine
    await engine.dispose()
    logger.info("Marketing Agent service stopped")


# Create FastAPI app
app = FastAPI(
    title="Marketing Agent",
    description="Content drafting and Ghost CMS publishing pipeline",
    version="0.1.0",
    lifespan=lifespan,
)


# Health check
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "marketing-agent",
        "version": "0.1.0",
    }


# Include routers with API prefix
app.include_router(signals_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(topics_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(drafts_router, prefix="/api/v1", dependencies=[Depends(get_db)])


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("MARKETING_PORT", 8210))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
