"""Marketing Agent FastAPI service — Phase 0 scaffold."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from api import signals, topics, drafts
from api import scout
from app.scout.events import init_nats_publisher, close_nats_publisher
from app.scout.scheduler import get_scheduler
from config import settings
from database import engine
from models import Base

# Configure logging
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Marketing Agent starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")

    # Initialize Scout Engine
    if settings.scout_enabled:
        logger.info("Initializing Scout Engine...")

        # Initialize NATS publisher
        await init_nats_publisher(settings.nats_url)

        # Start scheduler
        scheduler = get_scheduler()
        try:
            await scheduler.start()
            logger.info("Scout scheduler started successfully")
        except Exception as e:
            logger.error(f"Failed to start Scout scheduler: {e}")

    yield

    # Shutdown
    logger.info("Marketing Agent shutting down...")

    # Stop Scout Engine
    if settings.scout_enabled:
        logger.info("Shutting down Scout Engine...")
        scheduler = get_scheduler()
        await scheduler.stop()
        await close_nats_publisher()


# Create FastAPI app
app = FastAPI(
    title="Marketing Agent",
    description="Phase 0 — Ghost CMS + FastAPI scaffold for marketing pipeline",
    version="0.1.0",
    lifespan=lifespan,
)


# Health check endpoint
@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "marketing-agent",
        "version": "0.1.0",
    }


# Include routers
app.include_router(signals.router, prefix="/api/v1")
app.include_router(topics.router, prefix="/api/v1")
app.include_router(drafts.router, prefix="/api/v1")
app.include_router(scout.router, prefix="/api/v1")


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.marketing_port,
        log_level=settings.log_level.lower(),
    )
