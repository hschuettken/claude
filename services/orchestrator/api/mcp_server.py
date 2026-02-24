"""MCP (Model Context Protocol) server for the orchestrator.

Exposes all orchestrator tools as MCP tools and key data as MCP resources.
Uses the low-level mcp Server API for full control over tool schemas
(dynamic registration from TOOL_DEFINITIONS).

Mounted into the FastAPI app at /mcp via SSE transport.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import Resource, TextContent, Tool

from shared.log import get_logger

from tools import TOOL_DEFINITIONS

logger = get_logger("api.mcp")

# Module-level references, set by configure().
_tool_executor: Any = None
_brain: Any = None
_settings: Any = None
_service_states: dict[str, dict[str, Any]] = {}
_activity: Any = None


def configure(
    tool_executor: Any,
    brain: Any,
    settings: Any,
    service_states: dict[str, dict[str, Any]],
    activity: Any,
) -> None:
    """Wire up shared components."""
    global _tool_executor, _brain, _settings, _service_states, _activity
    _tool_executor = tool_executor
    _brain = brain
    _settings = settings
    _service_states = service_states
    _activity = activity


def create_mcp_server() -> Server:
    """Create and configure the MCP server with tools and resources."""
    server = Server("homelab-orchestrator")

    # ----------------------------------------------------------------
    # Tools — all 23 from TOOL_DEFINITIONS + chat_with_orchestrator
    # ----------------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for td in TOOL_DEFINITIONS:
            func = td.get("function", {})
            name = func.get("name", "")
            if not name:
                continue
            tools.append(Tool(
                name=name,
                description=func.get("description", ""),
                inputSchema=func.get("parameters", {"type": "object", "properties": {}}),
            ))
        # Special chat tool — only available when Brain is enabled
        if _brain is not None:
            tools.append(Tool(
                name="chat_with_orchestrator",
                description=(
                    "Send a natural-language message to the home orchestrator AI. "
                    "The AI will reason about the request, call internal tools as "
                    "needed (energy data, forecasts, HA control, calendar, memory), "
                    "and return a natural-language response. Use this for complex "
                    "questions that require reasoning across multiple data sources."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message or question to process",
                        },
                        "user_name": {
                            "type": "string",
                            "description": "Name of the caller (default: MCP)",
                            "default": "MCP",
                        },
                    },
                    "required": ["message"],
                },
            ))
        return tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None = None,
    ) -> list[TextContent]:
        args = arguments or {}

        # Chat tool goes through the full Brain (if enabled)
        if name == "chat_with_orchestrator":
            if _brain is None:
                return [TextContent(
                    type="text",
                    text=(
                        "Orchestrator is running in headless mode; chat reasoning is disabled. "
                        "Use direct tools instead (MCP/REST)."
                    ),
                )]
            message = args.get("message", "")
            user_name = args.get("user_name", "MCP")
            logger.info("mcp_chat", user=user_name, msg_len=len(message))
            response = await _brain.process_message(
                message, chat_id="mcp", user_name=user_name,
            )
            return [TextContent(type="text", text=response)]

        # All other tools go through ToolExecutor
        logger.info("mcp_tool_call", tool=name, args=args)
        result = await _tool_executor.execute(name, args)
        return [TextContent(type="text", text=result)]

    # ----------------------------------------------------------------
    # Resources — read-only data snapshots
    # ----------------------------------------------------------------

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="homelab://status",
                name="Orchestrator Status",
                description="Current orchestrator status, activity metrics, and service states",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://energy",
                name="Home Energy Summary",
                description="Current energy state: PV production, grid, battery, EV, house consumption",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://pv-forecast",
                name="PV Forecast",
                description="Solar production forecast for today and tomorrow with hourly breakdown",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://ev-charging",
                name="EV Charging Status",
                description="Current EV charge mode, power, session energy, departure time",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://ev-forecast",
                name="EV Forecast Plan",
                description="EV driving forecast, predicted trips, and charging plan for the next 3 days",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://weather",
                name="Weather Forecast",
                description="Current weather and short-term forecast",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://energy-prices",
                name="Energy Prices",
                description="Current energy prices: grid buy, feed-in tariff, EPEX spot, oil heating",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://tools",
                name="Available Tools",
                description="Complete list of orchestrator tools with parameter schemas",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://ha/entities",
                name="Home Assistant Entities",
                description="Pass-through listing of all Home Assistant entities",
                mimeType="application/json",
            ),
            Resource(
                uri="homelab://ha/services",
                name="Home Assistant Services",
                description="Pass-through listing of all Home Assistant service domains and services",
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        uri_str = str(uri)

        if uri_str == "homelab://status":
            online = [
                s for s, st in _service_states.items()
                if st.get("status") == "online"
            ]
            return json.dumps({
                "status": "online",
                "llm_provider": _settings.llm_provider,
                "activity": _activity.to_dict(),
                "services_online": len(online),
                "services_tracked": len(_service_states),
                "service_states": _service_states,
            }, default=str)

        if uri_str == "homelab://energy":
            return await _tool_executor.execute("get_home_energy_summary", {})

        if uri_str == "homelab://pv-forecast":
            return await _tool_executor.execute("get_pv_forecast", {})

        if uri_str == "homelab://ev-charging":
            return await _tool_executor.execute("get_ev_charging_status", {})

        if uri_str == "homelab://ev-forecast":
            return await _tool_executor.execute("get_ev_forecast_plan", {})

        if uri_str == "homelab://weather":
            return await _tool_executor.execute("get_weather_forecast", {})

        if uri_str == "homelab://energy-prices":
            return await _tool_executor.execute("get_energy_prices", {})

        if uri_str == "homelab://tools":
            tools = []
            for td in TOOL_DEFINITIONS:
                func = td.get("function", {})
                tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })
            return json.dumps(tools)

        if uri_str == "homelab://ha/entities":
            return await _tool_executor.execute("list_ha_entities", {"limit": 500})

        if uri_str == "homelab://ha/services":
            return await _tool_executor.execute("list_ha_services", {})

        raise ValueError(f"Unknown resource: {uri_str}")

    return server
