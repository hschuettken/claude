"""Tests for calendar_interpreter — cache, hashing, low-confidence gate (S6a)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from calendar_interpreter import CalendarInterpreter, event_content_hash


def test_event_content_hash_stable():
    event = {"summary": "H: Aachen", "start": "2026-04-29T07:00", "location": ""}
    h1 = event_content_hash(event)
    h2 = event_content_hash(dict(event))
    assert h1 == h2
    # Changing summary changes hash
    event2 = {**event, "summary": "H: Münster"}
    assert event_content_hash(event2) != h1


def test_is_high_confidence_threshold():
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path="/tmp/test_cache.json",
        confidence_threshold=0.8,
    )
    assert interp.is_high_confidence({"ev_confidence": 0.9}) is True
    assert interp.is_high_confidence({"ev_confidence": 0.79}) is False
    assert interp.is_high_confidence({"ev_confidence": 0.8}) is True
    assert interp.is_high_confidence(None) is False
    assert interp.is_high_confidence({}) is False


def test_is_high_confidence_invalid_value():
    interp = CalendarInterpreter(
        router_url="http://x", cache_path="/tmp/test_cache.json"
    )
    assert interp.is_high_confidence({"ev_confidence": "not-a-number"}) is False


@pytest.mark.asyncio
async def test_interpret_returns_none_for_eventless_input(tmp_path: Path):
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(tmp_path / "cache.json"),
    )
    assert await interp.interpret({"summary": "no id"}) is None


@pytest.mark.asyncio
async def test_interpret_uses_cache_when_hash_matches(tmp_path: Path):
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(tmp_path / "cache.json"),
    )
    event = {"id": "evt1", "summary": "H: Aachen"}
    chash = event_content_hash(event)
    interp._cache["evt1"] = {
        "hash": chash,
        "interp": {"person": "henning", "ev_confidence": 0.95},
    }
    # _call_llm should NOT be invoked when cache hits
    with patch.object(
        interp, "_call_llm", new=AsyncMock(side_effect=AssertionError("called"))
    ):
        result = await interp.interpret(event)
    assert result == {"person": "henning", "ev_confidence": 0.95}


@pytest.mark.asyncio
async def test_interpret_calls_llm_and_persists_on_cache_miss(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(cache_path),
    )
    event = {"id": "evt2", "summary": "N: Lengerich"}
    fake_interp = {
        "person": "nicole",
        "destination_name": "Lengerich",
        "estimated_distance_km": 22.0,
        "ev_likely": True,
        "ev_confidence": 0.92,
        "reason": "regular commute",
    }
    with patch.object(interp, "_call_llm", new=AsyncMock(return_value=fake_interp)):
        result = await interp.interpret(event)
    assert result == fake_interp
    # Cache file persisted
    assert cache_path.exists()
    persisted = json.loads(cache_path.read_text())
    assert persisted["evt2"]["interp"]["destination_name"] == "Lengerich"


@pytest.mark.asyncio
async def test_interpret_recomputes_when_event_content_changes(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(cache_path),
    )
    # Pre-seed with stale interpretation
    old_event = {"id": "evt3", "summary": "old summary"}
    interp._cache["evt3"] = {
        "hash": event_content_hash(old_event),
        "interp": {"person": "henning"},
    }
    # New event has different summary — different hash → recompute
    new_event = {"id": "evt3", "summary": "new summary"}
    fresh_interp = {"person": "nicole", "ev_confidence": 0.5}
    with patch.object(interp, "_call_llm", new=AsyncMock(return_value=fresh_interp)):
        result = await interp.interpret(new_event)
    assert result == fresh_interp
    # Cache updated to new content
    assert interp._cache["evt3"]["interp"]["person"] == "nicole"


@pytest.mark.asyncio
async def test_interpret_returns_none_when_llm_fails(tmp_path: Path):
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(tmp_path / "cache.json"),
    )
    event = {"id": "evt4", "summary": "x"}
    with patch.object(
        interp, "_call_llm", new=AsyncMock(side_effect=RuntimeError("router down"))
    ):
        result = await interp.interpret(event)
    assert result is None
    # Cache should NOT contain a placeholder
    assert "evt4" not in interp._cache


@pytest.mark.asyncio
async def test_call_llm_strips_markdown_fences(tmp_path: Path):
    interp = CalendarInterpreter(
        router_url="http://x",
        cache_path=str(tmp_path / "cache.json"),
    )
    fake_data = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"person":"henning","ev_confidence":0.9}\n```'
                }
            }
        ]
    }
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value=fake_data)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return fake_resp

    with patch("calendar_interpreter.httpx.AsyncClient", FakeAsyncClient):
        result = await interp._call_llm({"summary": "H: Aachen"})
    assert result == {"person": "henning", "ev_confidence": 0.9}
