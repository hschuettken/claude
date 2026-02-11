"""Anthropic Claude LLM provider with tool-use support."""

from __future__ import annotations

import json
import uuid
from typing import Any

from anthropic import AsyncAnthropic

from llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.7,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        system_prompt = ""
        conversation: list[Message] = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content or ""
            else:
                conversation.append(msg)

        anthropic_messages = self._convert_messages(conversation)
        anthropic_tools = self._convert_tools(tools) if tools else []

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "temperature": self._temperature,
            "messages": anthropic_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert OpenAI-format tools to Anthropic format."""
        result: list[dict[str, Any]] = []
        for tool in tools:
            func = tool.get("function", tool)
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert unified messages to Anthropic format."""
        result: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                result.append({"role": "assistant", "content": content})

            elif msg.role == "tool":
                # Anthropic expects tool results as user messages with tool_result blocks
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                }
                # Merge consecutive tool results into one user message
                if result and result[-1].get("role") == "user":
                    last_content = result[-1]["content"]
                    if isinstance(last_content, list):
                        last_content.append(tool_result)
                        continue
                result.append({"role": "user", "content": [tool_result]})

        return result

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Anthropic response into our unified format."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
        )
