"""Daily Briefing — LLM-generated morning narrative.

Collects context (open threads, cognitive load, upcoming calendar events,
recent git commits, Orbit tasks due today) and asks the LLM Router to
generate a concise German-language morning briefing.

Uses qwen2.5:3b via the local llm-router (never Anthropic/OpenAI directly).
Result is cached in `daily_briefings` for the current date.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from . import db
from . import cognitive_load, continuity
from .config import settings
from .models import DailyBriefing

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du bist Hennings persönlicher Morgen-Assistent. Erstelle eine prägnante, \
motivierende Zusammenfassung des Tages in 3–5 Sätzen auf Deutsch. \
Fokus: Was liegt heute an? Was sind offene Fragen? Welcher kognitive Ballast kann abgebaut werden?"""


async def get_or_generate_briefing(target_date: Optional[date] = None) -> DailyBriefing:
    """Return today's briefing, generating it if not yet cached."""
    if target_date is None:
        target_date = date.today()

    cached = await _load_cached(target_date)
    if cached:
        return cached

    return await generate_briefing(target_date)


async def generate_briefing(target_date: Optional[date] = None) -> DailyBriefing:
    """Generate (or regenerate) the briefing for the given date."""
    if target_date is None:
        target_date = date.today()

    context = await _collect_context(target_date)
    narrative = await _call_llm(context)

    row = await db.fetchrow(
        """
        INSERT INTO daily_briefings (date, narrative, context)
        VALUES ($1, $2, $3)
        ON CONFLICT (date) DO UPDATE
            SET narrative = EXCLUDED.narrative,
                context   = EXCLUDED.context,
                generated_at = NOW()
        RETURNING *
        """,
        target_date,
        narrative,
        context,
    )
    if row:
        return _row_to_briefing(row)

    # Fallback if DB unavailable
    return DailyBriefing(
        id=__import__("uuid").uuid4(),
        date=target_date,
        narrative=narrative,
        context=context,
        generated_at=datetime.now(timezone.utc),
    )


async def _collect_context(today: date) -> dict[str, Any]:
    """Gather data points for the LLM prompt."""
    # Cognitive load
    try:
        load = await cognitive_load.compute()
        load_data = {"score": load.debt_score, "label": load.label}
    except Exception:
        load_data = {"score": 0, "label": "unknown"}

    # Open threads
    threads = await continuity.list_threads(status="open", limit=5)
    thread_titles = [t.title for t in threads]

    # Recent kg nodes (last 24h)
    recent_nodes = await db.fetch(
        """
        SELECT node_type, label FROM kg_nodes
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC LIMIT 10
        """,
    )
    recent = [{"type": r["node_type"], "label": r["label"]} for r in recent_nodes]

    return {
        "date": today.isoformat(),
        "cognitive_load": load_data,
        "open_threads": thread_titles,
        "recent_nodes": recent,
    }


async def _call_llm(context: dict[str, Any]) -> str:
    """Send context to llm-router and return the narrative text."""
    user_msg = (
        f"Kontext für {context['date']}:\n"
        f"- Kognitiver Belastungsgrad: {context['cognitive_load'].get('score', '?')} "
        f"({context['cognitive_load'].get('label', '?')})\n"
        f"- Offene Gedanken-Threads: {', '.join(context['open_threads']) or 'keine'}\n"
        f"- Aktuelle Aktivitäten: {json.dumps(context.get('recent_nodes', []), ensure_ascii=False)}\n\n"
        "Erstelle ein kurzes Tages-Briefing."
    )
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 300,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.llm_router_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
    except Exception as exc:
        logger.warning("briefing_llm_failed error=%s", exc)

    # Graceful fallback (no LLM)
    return _fallback_briefing(context)


def _fallback_briefing(ctx: dict[str, Any]) -> str:
    threads = ctx.get("open_threads", [])
    load = ctx.get("cognitive_load", {})
    return (
        f"Guten Morgen! Heute ist der {ctx.get('date', '')}. "
        f"Kognitiver Belastungsgrad: {load.get('label', 'unbekannt')} "
        f"({load.get('score', 0):.0f}/100). "
        + (f"Offene Threads: {', '.join(threads[:3])}." if threads else "Keine offenen Threads.")
    )


async def _load_cached(target_date: date) -> Optional[DailyBriefing]:
    row = await db.fetchrow("SELECT * FROM daily_briefings WHERE date = $1", target_date)
    return _row_to_briefing(row) if row else None


def _row_to_briefing(row: Any) -> DailyBriefing:
    return DailyBriefing(
        id=row["id"],
        date=row["date"],
        narrative=row["narrative"],
        context=dict(row["context"]) if row["context"] else {},
        generated_at=row["generated_at"],
    )
