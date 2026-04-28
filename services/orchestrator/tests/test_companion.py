"""Tests for Kairos companion agent module.

Covers: router endpoints, persona builder, cost tracker.
All external dependencies (Postgres, Redis, NATS, LLM) are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_chat_engine(final_content: str = "Hello from Kairos") -> MagicMock:
    """Build a mocked ChatEngine that yields a simple message + done event."""

    async def _fake_chat(**kwargs):
        yield {"type": "thinking", "text": "thinking..."}
        yield {"type": "message", "role": "assistant", "content": final_content}
        yield {
            "type": "done",
            "session_id": kwargs.get("session_id", "s1"),
            "tokens_used": 42,
        }

    engine = MagicMock()
    engine.chat = _fake_chat
    engine.memory = AsyncMock()
    return engine


def _make_dispatch_manager(dispatch_id: str = "d1") -> AsyncMock:
    manager = AsyncMock()
    manager.create_dispatch.return_value = dispatch_id
    manager.get_dispatch.return_value = {
        "id": dispatch_id,
        "status": "pending",
        "session_id": "s1",
        "prompt_excerpt": "Fix the bug",
    }
    manager.list_dispatches.return_value = []
    return manager


# ---------------------------------------------------------------------------
# Test 1: POST /companion/sessions — creates session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_returns_session_id():
    """Router returns a session_id when MemoryManager.create_session succeeds."""
    from companion import router as router_module

    session_id = "test-session-abc"
    engine = _make_chat_engine()
    engine.memory.create_session = AsyncMock(return_value=session_id)
    engine.memory.get_session = AsyncMock(
        return_value={"id": session_id, "created_at": "2026-04-12T00:00:00Z"}
    )

    router_module._chat_engine = engine
    router_module._dispatch_manager = _make_dispatch_manager()

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/sessions", json={"user_id": "henning", "title": "Test"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["session_id"] == session_id


# ---------------------------------------------------------------------------
# Test 2: POST /companion/sessions/{id}/chat — returns response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_response():
    """Sync chat endpoint aggregates streaming events and returns final response."""
    from companion import router as router_module

    engine = _make_chat_engine(final_content="42 kWh remaining")
    router_module._chat_engine = engine
    router_module._dispatch_manager = _make_dispatch_manager()

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/sessions/s1/chat",
            json={"user_id": "henning", "message": "How much battery?"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "42 kWh remaining"
    assert body["session_id"] == "s1"
    assert body["tokens_used"] == 42


# ---------------------------------------------------------------------------
# Test 3: GET /companion/sessions/{id}/messages — lists messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_returns_list():
    """Messages endpoint returns a messages list for a session."""
    from companion import router as router_module

    engine = _make_chat_engine()
    engine.memory.get_recent_messages = AsyncMock(return_value=[])
    router_module._chat_engine = engine
    router_module._dispatch_manager = _make_dispatch_manager()

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router_module.router)

    with TestClient(app) as client:
        resp = client.get("/companion/sessions/s1/messages")

    assert resp.status_code == 200
    body = resp.json()
    assert "messages" in body
    assert isinstance(body["messages"], list)


# ---------------------------------------------------------------------------
# Test 4: POST /companion/dispatch — creates dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_dispatch():
    """Dispatch endpoint creates a record and returns dispatch_id."""
    from companion import router as router_module

    dispatch_id = "dispatch-xyz"
    engine = _make_chat_engine()
    dispatch_mgr = _make_dispatch_manager(dispatch_id=dispatch_id)
    router_module._chat_engine = engine
    router_module._dispatch_manager = dispatch_mgr

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/dispatch",
            json={
                "session_id": "s1",
                "prompt": "Fix the memory leak",
                "branch": "fix/memory",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dispatch_id"] == dispatch_id
    assert body["status"] == "pending"


# ---------------------------------------------------------------------------
# Test 5: PersonaBuilder builds non-empty prompt containing "Kairos"
# ---------------------------------------------------------------------------


def test_persona_builder():
    """PersonaBuilder.build() returns a non-trivial prompt mentioning Kairos."""
    from companion.persona import PersonaBuilder

    builder = PersonaBuilder(persona_notes="Test persona, likes concise answers")
    prompt = builder.build(hot_state={}, tools=[])
    assert "Kairos" in prompt
    assert len(prompt) > 100


def test_persona_builder_with_hot_state():
    """PersonaBuilder injects energy data from hot_state."""
    from companion.persona import PersonaBuilder

    builder = PersonaBuilder()
    hot = {
        "energy": {
            "solar_power_w": 3000,
            "battery_soc_percent": 85,
            "grid_power_w": 200,
        }
    }
    prompt = builder.build(hot_state=hot, tools=[])
    assert "3000" in prompt
    assert "85" in prompt


# ---------------------------------------------------------------------------
# Test 6: CostTracker — cap detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_tracker_cap_reached():
    """CostTracker.is_cap_reached() returns True when usage >= daily_cap."""
    from companion.cost import CostTracker

    mock_redis = AsyncMock()
    # get() returns bytes representing a value above cap
    mock_redis.get = AsyncMock(return_value=b"600000")

    tracker = CostTracker(mock_redis, daily_cap=500_000)
    result = await tracker.is_cap_reached("henning")
    assert result is True


@pytest.mark.asyncio
async def test_cost_tracker_cap_not_reached():
    """CostTracker.is_cap_reached() returns False when usage is below cap."""
    from companion.cost import CostTracker

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"10000")

    tracker = CostTracker(mock_redis, daily_cap=500_000)
    result = await tracker.is_cap_reached("henning")
    assert result is False


@pytest.mark.asyncio
async def test_cost_tracker_record_returns_status():
    """CostTracker.record() returns a CostStatus with correct fields."""
    from companion.cost import CostTracker, CostStatus

    mock_redis = AsyncMock()
    # cost.py uses: pipe = self._redis.pipeline(); pipe.incrby(); pipe.expire(); await pipe.execute()
    # pipeline() returns a plain mock; execute() is awaited
    pipe_mock = MagicMock()
    pipe_mock.incrby = MagicMock()
    pipe_mock.expire = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[50000, True, 5000, True])
    mock_redis.pipeline = MagicMock(return_value=pipe_mock)

    tracker = CostTracker(mock_redis, daily_cap=500_000)
    status = await tracker.record("henning", "session-1", 5000)

    assert isinstance(status, CostStatus)
    assert status.daily_tokens == 50000
    assert status.capped is False
    assert status.warning is False  # 50k / 500k = 10% — below 80% threshold


# ---------------------------------------------------------------------------
# Test 7: HenningGPT has Kairos proxy pattern
# ---------------------------------------------------------------------------


def test_henninggpt_has_kairos_proxy():
    """Verify HenningGPT router file contains Kairos proxy endpoint code."""
    import os

    # Support both developer machine and CI/container environments
    candidates = [
        "/home/hesch/dev/projects/nb9os/services/nb9os/src/backend/app/api/henning_gpt.py",
        "/repos/nb9os/services/nb9os/src/backend/app/api/henning_gpt.py",
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if path is None:
        pytest.skip("henning_gpt.py not found in any expected location")

    with open(path) as fh:
        content = fh.read()
    assert "kairos" in content.lower(), "henning_gpt.py must reference 'kairos'"
    # Either direct URL or variable name — both patterns are acceptable
    assert "192.168.0.50:8050" in content or "orchestrator" in content.lower(), (
        "henning_gpt.py must reference orchestrator URL or name"
    )
