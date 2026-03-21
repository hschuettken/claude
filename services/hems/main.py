"""HEMS — Home Energy Management System service.

Exposes REST API for energy schedule management, mode control,
and status reporting. Coordinates with Home Assistant and the
central Orchestrator.

Endpoints:
  GET  /health
  GET  /api/v1/hems/status
  GET  /api/v1/hems/schedule
  POST /api/v1/hems/schedule
  GET  /api/v1/hems/mode
  POST /api/v1/hems/mode
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from config import HEMSSettings
from routes import router

HEALTHCHECK_FILE = Path(os.environ.get("HEMS_DATA_DIR", "/app/data")) / "healthcheck"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hems")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: HEMSSettings = app.state.settings
    logger.info("HEMS starting up — mode=%s", settings.hems_mode)
    HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTHCHECK_FILE.touch()
    yield
    logger.info("HEMS shutting down")
    HEALTHCHECK_FILE.unlink(missing_ok=True)


def create_app() -> FastAPI:
    settings = HEMSSettings()
    app = FastAPI(
        title="HEMS",
        description="Home Energy Management System",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(router)
    return app


async def main() -> None:
    app = create_app()
    settings: HEMSSettings = app.state.settings
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
