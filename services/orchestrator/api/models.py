"""Pydantic models for REST API requests and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ConfigDict, model_validator


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
    """Tool execution request.

    Accepts both modern and legacy field names:
    - tool_name + arguments
    - tool + parameters
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    tool_name: str = Field(alias="tool")
    arguments: dict[str, Any] = Field(default_factory=dict, alias="parameters")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # If caller sends `tool_name`, keep compatibility.
        if "tool_name" in data and "tool" not in data:
            data["tool"] = data["tool_name"]

        # If caller sends `arguments`, keep compatibility.
        if "arguments" in data and "parameters" not in data:
            data["parameters"] = data["arguments"]

        return data


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
