"""Tests for llm/router_llm.py — RouterLLMProvider.

Covers:
- Happy path: router returns content, no tool calls
- Tool call parsing: router returns tool_calls, parsed to ToolCall dataclasses
- No-temperature assertion: the payload sent to router never contains 'temperature'
- Fallback: router 503 raises httpx.HTTPStatusError (clean, no crash)
- Factory: create_provider with anthropic provider returns RouterLLMProvider
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm.base import Message, ToolCall
from llm.router_llm import RouterLLMProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_router_response(content: str = "Hello from router") -> dict:
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "tool_calls": []},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _make_tool_response(tool_name: str, tool_args: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


# ---------------------------------------------------------------------------
# Happy path — text response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_text_response():
    """Router returns text content → LLMResponse.content is populated."""
    provider = RouterLLMProvider(router_url="http://llm-router:8070", model="sonnet")
    messages = [
        Message(role="user", content="What is 2+2?"),
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_router_response("The answer is 4.")
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await provider.chat(messages)

    assert result.content == "The answer is 4."
    assert result.tool_calls == []


# ---------------------------------------------------------------------------
# No temperature in payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_temperature_in_request_payload():
    """The payload sent to the router must never contain 'temperature'."""
    provider = RouterLLMProvider(router_url="http://llm-router:8070", model="opus")
    messages = [Message(role="user", content="Think hard.")]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_router_response("OK")
    mock_resp.raise_for_status = MagicMock()

    captured_payload: dict = {}

    async def _capture_post(url, *, json=None, **kwargs):
        captured_payload.update(json or {})
        return mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = _capture_post
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        await provider.chat(messages)

    assert "temperature" not in captured_payload, (
        "temperature must NOT be sent to the router — Opus 4.7 returns 400 on temperature="
    )
    assert captured_payload.get("model") == "opus"
    assert captured_payload.get("stream") is False


# ---------------------------------------------------------------------------
# Tool call parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_parsed_correctly():
    """Router returns tool_calls → parsed into ToolCall dataclasses."""
    provider = RouterLLMProvider(router_url="http://llm-router:8070", model="sonnet")
    messages = [Message(role="user", content="Turn on the light.")]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_tool_response(
        "call_ha_service", {"entity_id": "light.living_room", "service": "turn_on"}
    )
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await provider.chat(messages)

    assert len(result.tool_calls) == 1
    tc: ToolCall = result.tool_calls[0]
    assert tc.name == "call_ha_service"
    assert tc.arguments["entity_id"] == "light.living_room"
    assert tc.id == "call_abc"


# ---------------------------------------------------------------------------
# Router 503 raises clean error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_503_raises_http_status_error():
    """Router 503 → raises httpx.HTTPStatusError (not swallowed, not a crash)."""
    provider = RouterLLMProvider(router_url="http://llm-router:8070", model="sonnet")
    messages = [Message(role="user", content="Test")]

    error_resp = MagicMock()
    error_resp.status_code = 503
    error_resp.text = "Service Unavailable"
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=error_resp
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(httpx.HTTPStatusError):
            await provider.chat(messages)


# ---------------------------------------------------------------------------
# Factory — anthropic provider returns RouterLLMProvider
# ---------------------------------------------------------------------------


def test_create_provider_anthropic_returns_router_provider():
    """Factory must return RouterLLMProvider (not AnthropicProvider) for anthropic."""
    from llm import create_provider

    settings = MagicMock()
    settings.llm_provider = "anthropic"
    settings.llm_router_url = "http://llm-router:8070"
    settings.anthropic_model = "sonnet"
    settings.llm_max_tokens = 4096

    provider = create_provider(settings)

    assert isinstance(provider, RouterLLMProvider), (
        f"Expected RouterLLMProvider, got {type(provider).__name__}"
    )


def test_create_provider_anthropic_no_temperature_attr():
    """RouterLLMProvider must NOT have _temperature attribute."""
    from llm import create_provider

    settings = MagicMock()
    settings.llm_provider = "anthropic"
    settings.llm_router_url = "http://llm-router:8070"
    settings.anthropic_model = "opus"
    settings.llm_max_tokens = 8192

    provider = create_provider(settings)

    assert not hasattr(provider, "_temperature"), (
        "RouterLLMProvider must not have _temperature — temperature must never be forwarded"
    )


# ---------------------------------------------------------------------------
# Message conversion: system messages handled
# ---------------------------------------------------------------------------


def test_convert_messages_system_becomes_system_role():
    """System messages must be passed as role=system in OpenAI format."""
    provider = RouterLLMProvider(router_url="http://llm-router:8070", model="sonnet")
    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello"),
    ]

    converted = provider._convert_messages(messages)

    assert converted[0]["role"] == "system"
    assert converted[0]["content"] == "You are a helpful assistant."
    assert converted[1]["role"] == "user"
