"""REST API routes for the orchestrator.

Endpoints:
    GET  /_health               -- Docker healthcheck (no auth)
    GET  /api/v1/status         -- Service status and activity
    GET  /api/v1/tools          -- List available tools
    POST /api/v1/tools/execute  -- Execute a single tool directly
    POST /api/v1/chat           -- Full Brain reasoning (like Telegram)
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

from shared.log import get_logger

from api.models import (
    ChatRequest,
    ChatResponse,
    ServiceStatus,
    ToolInfo,
    ToolListResponse,
    ToolRequest,
    ToolResponse,
)
from tools import TOOL_DEFINITIONS

logger = get_logger("api.routes")

router = APIRouter(prefix="/api/v1", tags=["orchestrator"])

# Wired up by configure() at startup — avoids circular imports.
_brain: Any = None
_tool_executor: Any = None
_activity: Any = None
_settings: Any = None
_service_states: dict[str, dict[str, Any]] = {}
_start_time: float = 0.0


def configure(
    brain: Any,
    tool_executor: Any,
    activity: Any,
    settings: Any,
    service_states: dict[str, dict[str, Any]],
    start_time: float,
) -> None:
    """Wire up shared components. Called once during server setup."""
    global _brain, _tool_executor, _activity, _settings, _service_states, _start_time
    _brain = brain
    _tool_executor = tool_executor
    _activity = activity
    _settings = settings
    _service_states = service_states
    _start_time = start_time


@router.get("/status", response_model=ServiceStatus)
async def get_status() -> ServiceStatus:
    """Service status and activity summary."""
    online = [
        s for s, state in _service_states.items()
        if state.get("status") == "online"
    ]
    return ServiceStatus(
        status="online",
        uptime_seconds=round(time.monotonic() - _start_time, 1),
        llm_provider=("headless" if _brain is None else _settings.llm_provider),
        messages_today=_activity.messages_today,
        tools_today=_activity.tools_today,
        suggestions_today=_activity.suggestions_today,
        services_tracked=len(_service_states),
        services_online=len(online),
    )


@router.get("/tools", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """List all available LLM tools with their schemas."""
    tools = []
    for td in TOOL_DEFINITIONS:
        func = td.get("function", {})
        tools.append(ToolInfo(
            name=func.get("name", ""),
            description=func.get("description", ""),
            parameters=func.get("parameters", {}),
        ))
    return ToolListResponse(tools=tools, count=len(tools))


@router.post("/tools/execute", response_model=ToolResponse)
async def execute_tool(request: ToolRequest) -> ToolResponse:
    """Execute a single tool directly (bypasses LLM reasoning).

    Returns the raw tool result. Useful for programmatic access
    to specific data (energy summary, PV forecast, etc.).
    """
    logger.info("api_tool_execute", tool=request.tool_name)
    result_str = await _tool_executor.execute(
        request.tool_name, request.arguments,
    )
    try:
        result = json.loads(result_str)
    except json.JSONDecodeError:
        result = {"raw": result_str}
    return ToolResponse(tool_name=request.tool_name, result=result)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message through the Brain reasoning engine.

    This is the full LLM experience — identical to Telegram chat.
    The Brain builds context, calls tools as needed, and returns
    a natural-language response.
    """
    logger.info(
        "api_chat_request",
        chat_id=request.chat_id,
        user=request.user_name,
        msg_len=len(request.message),
    )
    if _brain is None:
        return ChatResponse(
            response=(
                "Orchestrator runs in headless mode. Chat reasoning is disabled; "
                "use /api/v1/tools/execute or MCP tools instead."
            ),
            chat_id=request.chat_id,
        )

    response = await _brain.process_message(
        request.message,
        chat_id=request.chat_id,
        user_name=request.user_name,
    )
    return ChatResponse(response=response, chat_id=request.chat_id)
