"""Abstract LLM provider interface.

Defines the common message/response types and the provider contract.
Each backend (Gemini, OpenAI, Anthropic, Ollama) implements ``LLMProvider``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A single tool/function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """Unified conversation message used across all providers.

    Roles:
        system    – system prompt (always first)
        user      – human message
        assistant – model response (may contain tool_calls)
        tool      – result of a tool execution
    """

    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # links tool result to its call
    name: str | None = None  # tool name (for tool role)


@dataclass
class LLMResponse:
    """Model response — either text content or tool calls (or both)."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# Tool definition format — OpenAI-compatible JSON Schema used as canonical form.
# Each provider converts to its native format.
ToolDefinition = dict[str, Any]


class LLMProvider(ABC):
    """Abstract base for LLM backends."""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        """Send a conversation and return the model's response.

        Args:
            messages: Conversation history (system + user + assistant + tool).
            tools: Available tool definitions in OpenAI-compatible format.

        Returns:
            LLMResponse with either text content or tool calls.
        """
