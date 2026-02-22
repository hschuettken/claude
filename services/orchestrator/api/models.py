"""Pydantic models for REST API requests and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Chat ---


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    chat_id: str = Field(default="api", max_length=100)
    user_name: str = Field(default="API", max_length=100)


class ChatResponse(BaseModel):
    response: str
    chat_id: str


# --- Tool execution ---


class ToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    tool_name: str
    result: Any


# --- Status ---


class ServiceStatus(BaseModel):
    status: str
    uptime_seconds: float
    llm_provider: str
    messages_today: int
    tools_today: int
    suggestions_today: int
    services_tracked: int
    services_online: int


# --- Tool listing ---


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolListResponse(BaseModel):
    tools: list[ToolInfo]
    count: int
