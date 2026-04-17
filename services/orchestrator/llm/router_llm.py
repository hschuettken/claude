"""LLM Router-backed provider for the orchestrator Brain.

Routes all Anthropic model calls through the llm-router service at :8070.
Uses the OpenAI-compat /v1/chat/completions endpoint.

Key difference from AnthropicProvider: NO temperature parameter is passed.
The router normalises parameters per-model (Opus 4.7 rejects temperature=).
Tool calls are represented in OpenAI format and parsed back to our unified type.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class RouterLLMProvider(LLMProvider):
    """LLM provider that delegates to llm-router via OpenAI-compat API.

    Supports all model aliases (opus, sonnet, haiku, quality, fast) the router
    understands.  Never passes temperature — the router handles capability
    normalisation so Opus 4.7's temperature restriction is transparently handled.
    """

    def __init__(
        self,
        router_url: str,
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> None:
        self._router_url = router_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        """Send conversation to llm-router and return a unified LLMResponse."""
        openai_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
            "stream": False,
            "cache": False,
            # NO temperature — router normalises per model capability
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._router_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "router_llm_http_error status=%d body=%.200s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("router_llm_transport_error error=%s", exc)
            raise

        return self._parse_response(data)

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert unified Message list to OpenAI-compat format."""
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
                result.append(entry)

            elif msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content or "",
                    }
                )

        return result

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse OpenAI-compat response into our unified LLMResponse."""
        choices = data.get("choices") or []
        if not choices:
            logger.warning("router_llm_empty_choices raw=%.200s", str(data))
            return LLMResponse(content=None, tool_calls=[])

        message = choices[0].get("message", {})
        content: str | None = message.get("content") or None

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or str(uuid.uuid4()),
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )

        return LLMResponse(content=content, tool_calls=tool_calls)
