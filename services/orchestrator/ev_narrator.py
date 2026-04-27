"""ev_narrator — LLM-generated 2-sentence narration for each plan_generated decision (S4.3).

Subscribes to ``energy.ev.decision.plan`` (the Decision Journal NATS publish),
calls the cheap LLM tier via llm-router, stores the narration in Redis under
``ev_narration:{trace_id}`` (30-day TTL) and updates ``ev_narration:latest``,
and publishes ``energy.ev.narration.published`` so dashboards can react.

Best-effort: any failure logs and proceeds. Never blocks the journal pipeline.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("ev_narrator")

NARRATOR_PROMPT = (
    "You are the EV charging assistant narrator. Given the plan JSON, write "
    "EXACTLY two sentences explaining (a) what's happening (b) why. Be specific "
    "about numbers and times. No markdown, no preamble."
)

REDIS_NARRATION_KEY = "ev_narration:{trace_id}"
REDIS_LATEST_KEY = "ev_narration:latest"
NARRATION_TTL_SECONDS = 30 * 24 * 3600


class EVNarrator:
    """LLM-narrate every EV plan and store under Redis + republish on NATS."""

    def __init__(
        self,
        nats: Any,
        redis_client: Any,
        llm_router_url: str,
        model: str = "haiku",
        max_tokens: int = 160,
    ) -> None:
        self._nats = nats
        self._redis = redis_client
        self._router_url = llm_router_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens

    async def on_plan_journal(self, subject: str, payload: dict) -> None:
        trace_id = payload.get("trace_id")
        if not trace_id:
            return
        try:
            inputs_str = payload.get("inputs_json", "{}")
            try:
                inputs = (
                    json.loads(inputs_str)
                    if isinstance(inputs_str, str)
                    else inputs_str or {}
                )
            except (TypeError, json.JSONDecodeError):
                inputs = {}

            user_msg = json.dumps(
                {
                    "outcome": payload.get("outcome"),
                    "reason": payload.get("reason"),
                    "current_soc_pct": payload.get("current_soc_pct"),
                    "energy_needed_kwh": payload.get("energy_needed_kwh"),
                    "mode": payload.get("mode"),
                    "schedule": inputs.get("schedule", []),
                    "trips_today": inputs.get("trips_today", []),
                    "pv_forecast_today_kwh": inputs.get("pv_forecast_today_kwh"),
                },
                default=str,
            )

            narration = await self._llm_chat(user_msg)
            if not narration:
                return

            try:
                await self._redis.setex(
                    REDIS_NARRATION_KEY.format(trace_id=trace_id),
                    NARRATION_TTL_SECONDS,
                    narration,
                )
                await self._redis.set(REDIS_LATEST_KEY, str(trace_id))
            except Exception:
                logger.warning("narration_redis_write_failed", exc_info=True)

            await self._publish_narration(trace_id, narration)
            logger.info("narration_stored", trace_id=trace_id, length=len(narration))

        except Exception:
            logger.exception("narration_failed", trace_id=trace_id)

    async def _llm_chat(self, user_msg: str) -> str:
        """Call llm-router /v1/chat/completions with the cheap-tier model."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": NARRATOR_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": self._max_tokens,
            "stream": False,
            "cache": False,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                resp = await c.post(
                    f"{self._router_url}/v1/chat/completions", json=payload
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("narration_llm_call_failed", exc_info=True)
            return ""

        try:
            choices = data.get("choices") or []
            if not choices:
                return ""
            content = (choices[0].get("message", {}) or {}).get("content") or ""
            return content.strip()
        except Exception:
            logger.warning("narration_llm_parse_failed", exc_info=True)
            return ""

    async def _publish_narration(self, trace_id: str, narration: str) -> None:
        if not self._nats:
            return
        try:
            await self._nats.publish(
                "energy.ev.narration.published",
                {"trace_id": trace_id, "narration": narration},
            )
        except Exception:
            logger.warning(
                "narration_nats_publish_failed", trace_id=trace_id, exc_info=True
            )
