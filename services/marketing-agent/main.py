"""Marketing Agent FastAPI service — Phase 0 scaffold."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from api import signals, topics, drafts
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

    yield

    # Shutdown
    logger.info("Marketing Agent shutting down...")


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
