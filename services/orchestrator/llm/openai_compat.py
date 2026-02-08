"""OpenAI-compatible LLM provider.

Works with OpenAI, Azure OpenAI, and Ollama (via /v1 endpoint).
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        base_url: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = model
        self._temperature = temperature

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        oai_messages = self._convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert unified messages to OpenAI format."""
        result: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                result.append({"role": "system", "content": msg.content or ""})

            elif msg.role == "user":
                result.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    entry["content"] = msg.content
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                    if "content" not in entry:
                        entry["content"] = None
                result.append(entry)

            elif msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                })

        return result

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI response into our unified format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
        )
