"""
Backend Service — Core microservice for handling business logic.

Provides REST API with health checks, service status, and modular route structure.
Runs on port 8000.

Endpoints:
  GET  /health    — health check
  GET  /          — service info
  GET  /docs      — OpenAPI documentation
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app with documentation
app = FastAPI(
    title="Backend Service",
    description="Core microservice for business logic and API routing",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ============================================================================
# Models
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    timestamp: str = Field(..., description="Response timestamp (ISO 8601)")
    uptime_seconds: float | None = Field(None, description="Seconds since startup")


class ServiceInfo(BaseModel):
    """Service information response."""
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    status: str = Field(..., description="Current status")
    environment: str = Field(..., description="Environment (dev/staging/prod)")
    endpoints: dict[str, str] = Field(..., description="Available endpoints")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    timestamp: str = Field(..., description="Error timestamp (ISO 8601)")


# ============================================================================
# Global state
# ============================================================================

startup_time: datetime = None


# ============================================================================
# Lifecycle events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup."""
    global startup_time
    startup_time = datetime.utcnow()
    logger.info("Backend Service starting up...")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Backend Service shutting down...")


# ============================================================================
# Health & Info endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns service status and uptime information. Used by container orchestrators
    and monitoring systems to verify service availability.
    
    Returns:
        HealthResponse with status and uptime
    """
    uptime = None
    if startup_time:
        uptime = (datetime.utcnow() - startup_time).total_seconds()
    
    return HealthResponse(
        status="healthy",
        service="backend-service",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
        uptime_seconds=uptime,
    )


@app.get("/", response_model=ServiceInfo, tags=["info"])
async def root() -> ServiceInfo:
    """
    Service information endpoint.
    
    Provides metadata about the backend service, environment, and available endpoints.
    
    Returns:
        ServiceInfo with service details and endpoint references
    """
    return ServiceInfo(
        service="backend-service",
        version="1.0.0",
        status="running",
        environment=os.getenv("ENVIRONMENT", "development"),
        endpoints={
            "info": "/",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        },
    )


# ============================================================================
# Example routes (to be expanded with business logic)
# ============================================================================

@app.get("/status", tags=["status"])
async def status() -> dict[str, Any]:
    """
    Extended status endpoint.
    
    Provides detailed service status for monitoring and debugging.
    
    Returns:
        Status dictionary with service metrics
    """
    uptime = None
    if startup_time:
        uptime = (datetime.utcnow() - startup_time).total_seconds()
    
    return {
        "service": "backend-service",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "uptime_seconds": uptime,
        "python_version": os.sys.version.split()[0],
    }


# ============================================================================
# Error handlers
# ============================================================================

@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            error="Endpoint not found",
            status_code=404,
            timestamp=datetime.utcnow().isoformat() + "Z",
        ).dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            status_code=500,
            timestamp=datetime.utcnow().isoformat() + "Z",
        ).dict(),
    )


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    environment = os.getenv("ENVIRONMENT", "development")

    logger.info(f"Starting Backend Service on {host}:{port} ({environment})")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
