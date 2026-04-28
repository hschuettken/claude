"""LLM-based calendar event interpreter (S6a, FR #3064).

Parses ambiguous calendar entries via the LLM router (cheap tier) and
caches results in a JSON file keyed by event_id. The cache key is a
content-hash so we re-interpret if the event summary/location change.

When confidence ≥ 0.8 the trip predictor uses the LLM answer; otherwise
it falls back to the existing prefix-based parsing path.

We keep this self-contained inside ev-forecast to avoid cross-service
hops on the planning hot path. Future: migrate cache to Neo4j so other
services can reuse interpretations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("calendar_interpreter")

INTERP_SYSTEM_PROMPT = (
    "You parse a single calendar event for an EV-charging planner. "
    "Output ONLY a JSON object with these keys:\n"
    '{"person": "henning"|"nicole"|"shared"|"unknown", '
    '"destination_name": "...", '
    '"destination_city": "...", '
    '"estimated_distance_km": <float>, '
    '"ev_likely": <bool>, '
    '"ev_confidence": <0.0-1.0>, '
    '"reason": "<one short sentence>"}\n'
    "If the event is purely informational (a deadline, an at-home reminder, "
    "or a calendar block with no travel), set ev_likely=false and "
    "ev_confidence accordingly. Use known commute distances where possible."
)


def event_content_hash(event: dict) -> str:
    """Stable hash over the event's user-visible content."""
    h = hashlib.sha256()
    for k in ("summary", "start", "end", "location", "description"):
        h.update((str(event.get(k, "")) + "|").encode())
    return h.hexdigest()[:16]


class CalendarInterpreter:
    """Cached LLM-driven calendar interpreter using file-based persistence."""

    def __init__(
        self,
        router_url: str,
        cache_path: str | os.PathLike[str],
        *,
        model: str = "haiku",
        max_tokens: int = 200,
        confidence_threshold: float = 0.8,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._router_url = router_url.rstrip("/")
        self._cache_path = Path(cache_path)
        self._model = model
        self._max_tokens = max_tokens
        self._confidence_threshold = confidence_threshold
        self._timeout = timeout_seconds
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text())
        except Exception as exc:
            logger.warning("cache_load_failed", error=str(exc))
            return {}

    async def _persist_cache(self) -> None:
        async with self._lock:
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_text(json.dumps(self._cache, indent=2))
            except Exception as exc:
                logger.warning("cache_persist_failed", error=str(exc))

    async def interpret(self, event: dict) -> dict | None:
        """Return cached or fresh interpretation, or None on failure."""
        eid = event.get("id") or event.get("uid") or ""
        if not eid:
            return None
        chash = event_content_hash(event)
        cached = self._cache.get(eid)
        if cached and cached.get("hash") == chash:
            return cached.get("interp")

        try:
            interp = await self._call_llm(event)
        except Exception as exc:
            logger.warning("interpreter_llm_call_failed", error=str(exc), eid=eid)
            return None
        if interp is None:
            return None

        self._cache[eid] = {"hash": chash, "interp": interp}
        await self._persist_cache()
        return interp

    def is_high_confidence(self, interp: dict | None) -> bool:
        if not interp:
            return False
        try:
            return float(interp.get("ev_confidence", 0.0)) >= self._confidence_threshold
        except (TypeError, ValueError):
            return False

    async def _call_llm(self, event: dict) -> dict | None:
        user_payload = {
            k: event.get(k)
            for k in ("summary", "start", "end", "location", "description")
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": INTERP_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._router_url}/v1/chat/completions",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError):
            logger.warning("interpreter_no_choices", raw=str(data)[:200])
            return None
        # Strip markdown fences if any
        if content.startswith("```"):
            content = content.strip("`").strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("interpreter_invalid_json", content=content[:200])
            return None
