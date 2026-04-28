"""FastAPI application + MCP server setup.

Creates a single ASGI app that serves:
  /api/v1/*  -- REST API endpoints
  /mcp       -- MCP streamable HTTP transport
  /_health   -- Docker healthcheck

The server is started as a background asyncio task alongside
Telegram and ProactiveEngine.
"""

from __future__ import annotations

import asyncio
from typing import Any

import uvicorn
from fastapi import FastAPI

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from shared.log import get_logger

from api import routes, mcp_server, family as family_routes
from api.auth import APIKeyMiddleware

logger = get_logger("api.server")


def create_app(
    brain: Any,
    tool_executor: Any,
    activity: Any,
    settings: Any,
    service_states: dict[str, dict[str, Any]],
    start_time: float,
    companion_chat_engine: Any = None,
    companion_dispatch_manager: Any = None,
) -> FastAPI:
    """Build the FastAPI app with REST routes and MCP server mounted."""

    app = FastAPI(
        title="Homelab Orchestrator API",
        description=(
            "REST API and MCP server for the AI-powered home orchestrator. "
            "Provides programmatic access to energy data, forecasts, EV charging, "
            "Home Assistant control, and full LLM-powered reasoning."
        ),
        version="1.0.0",
    )

    # --- Auth middleware ---
    if settings.orchestrator_api_key:
        app.add_middleware(
            APIKeyMiddleware,
            api_key=settings.orchestrator_api_key,
        )
        logger.info("api_auth_enabled")
    else:
        logger.warning(
            "api_auth_disabled",
            reason="ORCHESTRATOR_API_KEY not set — all requests will be rejected",
        )
        # Add middleware that rejects everything (fail-closed)
        app.add_middleware(APIKeyMiddleware, api_key="__reject_all__")

    # --- Wire up REST routes ---
    routes.configure(
        brain=brain,
        tool_executor=tool_executor,
        activity=activity,
        settings=settings,
        service_states=service_states,
        start_time=start_time,
    )
    app.include_router(routes.router)

    # --- Family OS router ---
    family_routes.configure(
        ha=getattr(tool_executor, "ha", None),
        gcal=getattr(tool_executor, "gcal", None),
        orbit_tools=getattr(tool_executor, "_orbit_tools", None),
        energy_tools=getattr(tool_executor, "_energy_tools", None),
        settings=settings,
    )
    app.include_router(family_routes.router)

    # --- Companion router (Kairos) ---
    if companion_chat_engine is not None or companion_dispatch_manager is not None:
        try:
            from companion.router import router as companion_router

            app.include_router(companion_router)
            logger.info("companion_router_registered", prefix="/companion")
        except Exception as exc:
            logger.warning("companion_router_register_failed", error=str(exc))

    # --- Health endpoint (exempt from auth) ---
    @app.get("/_health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    # --- MCP server (streamable HTTP transport) ---
    mcp_server.configure(
        tool_executor=tool_executor,
        brain=brain,
        settings=settings,
        service_states=service_states,
        activity=activity,
    )
    server = mcp_server.create_mcp_server()

    # Mount MCP streamable HTTP transport
    manager = StreamableHTTPSessionManager(app=server)
    _mcp_state: dict = {}

    @app.on_event("startup")
    async def _start_mcp_manager() -> None:
        _mcp_state["ctx"] = manager.run()
        await _mcp_state["ctx"].__aenter__()
        logger.info("mcp_http_started", endpoint="/mcp")

    @app.on_event("shutdown")
    async def _stop_mcp_manager() -> None:
        ctx = _mcp_state.get("ctx")
        if ctx:
            await ctx.__aexit__(None, None, None)

    app.mount("/mcp", manager.handle_request)

    logger.info(
        "api_app_created",
        rest_prefix="/api/v1",
        mcp_mount="/mcp",
    )

    return app


async def start_api_server(
    app: FastAPI,
    host: str = "0.0.0.0",
    port: int = 8100,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run the API server as an asyncio task.

    Uses uvicorn with the programmatic Server API so it integrates
    with the existing event loop (no new process/thread).
    """
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    logger.info("api_server_starting", host=host, port=port)

    serve_task = asyncio.create_task(server.serve())

    if shutdown_event:
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [serve_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_task in done:
            server.should_exit = True
            await serve_task
        for task in pending:
            task.cancel()
    else:
        await serve_task

    logger.info("api_server_stopped")
