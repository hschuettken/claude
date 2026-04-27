"""Reflection Mode — daily / weekly / monthly LLM-generated reports.

Daily:   Compare planned (Orbit schedule) vs actual (git commits, calendar, HA presence)
Weekly:  Drift detector — compare current project allocation vs Life Area goals
Monthly: Life momentum score — aggregate goal progress, "are you on track?"

Uses the llm-router (qwen2.5:3b by default) for narrative generation.
Reports are cached in `reflection_reports` with UNIQUE (period_type, period_start).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from . import db
from .config import settings
from .models import ReflectionReport

logger = logging.getLogger(__name__)

_SYSTEM_REFLECTION = """\
Du bist Hennings persönlicher Lebens-Coach und Reflexions-Assistent. \
Analysiere die bereitgestellten Daten und erstelle einen ehrlichen, \
konstruktiven Bericht auf Deutsch. Sei präzise und handlungsorientiert."""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def get_or_generate_daily(target_date: Optional[date] = None) -> ReflectionReport:
    target_date = target_date or date.today()
    cached = await _load_cached("daily", target_date, target_date)
    if cached:
        return cached
    metrics = await _daily_metrics(target_date)
    content = await _generate("daily", metrics)
    return await _save(
        period_type="daily",
        period_start=target_date,
        period_end=target_date,
        content=content,
        metrics=metrics,
    )


async def get_or_generate_weekly(week_start: Optional[date] = None) -> ReflectionReport:
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)
    cached = await _load_cached("weekly", week_start, week_end)
    if cached:
        return cached
    metrics = await _weekly_metrics(week_start, week_end)
    content = await _generate("weekly", metrics)
    return await _save(
        period_type="weekly",
        period_start=week_start,
        period_end=week_end,
        content=content,
        metrics=metrics,
    )


async def get_or_generate_monthly(year: Optional[int] = None, month: Optional[int] = None) -> ReflectionReport:
    today = date.today()
    year = year or today.year
    month = month or today.month
    period_start = date(year, month, 1)
    # Last day of month
    if month == 12:
        period_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(year, month + 1, 1) - timedelta(days=1)
    cached = await _load_cached("monthly", period_start, period_end)
    if cached:
        return cached
    metrics = await _monthly_metrics(period_start, period_end)
    content = await _generate("monthly", metrics)
    return await _save(
        period_type="monthly",
        period_start=period_start,
        period_end=period_end,
        content=content,
        metrics=metrics,
    )


async def list_reports(period_type: Optional[str] = None, limit: int = 20) -> list[ReflectionReport]:
    if period_type:
        rows = await db.fetch(
            "SELECT * FROM reflection_reports WHERE period_type = $1 ORDER BY period_start DESC LIMIT $2",
            period_type, limit,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM reflection_reports ORDER BY period_start DESC LIMIT $1",
            limit,
        )
    return [_row_to_report(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Metrics collection
# ─────────────────────────────────────────────────────────────────────────────

async def _daily_metrics(day: date) -> dict[str, Any]:
    """Compare planned (Orbit) vs actual (git + HA presence) for a day."""
    day_str = day.isoformat()

    # Git commits on this day
    commits = await db.fetch(
        """
        SELECT label, properties->>'author' as author
        FROM kg_nodes
        WHERE node_type = 'git_commit'
          AND (properties->>'date')::text LIKE $1
        LIMIT 20
        """,
        f"{day_str}%",
    )

    # Orbit tasks completed
    tasks_done = await db.fetch(
        """
        SELECT label FROM kg_nodes
        WHERE node_type = 'orbit_task'
          AND (properties->>'completed_at')::text LIKE $1
        LIMIT 20
        """,
        f"{day_str}%",
    )

    # Calendar events
    calendar_events = await db.fetch(
        """
        SELECT label FROM kg_nodes
        WHERE node_type IN ('meeting', 'calendar_event')
          AND (properties->>'start')::text LIKE $1
        LIMIT 10
        """,
        f"{day_str}%",
    )

    # Presence (HA events)
    presence_events = await db.fetch(
        """
        SELECT label FROM kg_nodes
        WHERE node_type = 'ha_event'
          AND label LIKE 'person%'
          AND created_at::date = $1
        LIMIT 10
        """,
        day_str,
    )

    return {
        "date": day_str,
        "git_commits": [r["label"] for r in commits],
        "tasks_completed": [r["label"] for r in tasks_done],
        "calendar_events": [r["label"] for r in calendar_events],
        "presence_changes": [r["label"] for r in presence_events],
    }


async def _weekly_metrics(week_start: date, week_end: date) -> dict[str, Any]:
    """Drift detector: project allocation vs Life Area goals."""
    ws, we = week_start.isoformat(), week_end.isoformat()

    # Commits per repo
    commits_by_repo = await db.fetch(
        """
        SELECT properties->>'repo' as repo, COUNT(*) as cnt
        FROM kg_nodes
        WHERE node_type = 'git_commit'
          AND (properties->>'date')::text BETWEEN $1 AND $2
        GROUP BY repo
        ORDER BY cnt DESC
        """,
        ws, we,
    )

    # Goals and their progress
    goals = await db.fetch(
        """
        SELECT label, properties->>'area' as area, properties->>'progress' as progress
        FROM kg_nodes
        WHERE node_type = 'orbit_goal'
        ORDER BY label
        LIMIT 20
        """,
    )

    # Tasks completed this week
    tasks = await db.fetch(
        """
        SELECT COUNT(*) as cnt FROM kg_nodes
        WHERE node_type = 'orbit_task'
          AND (properties->>'completed_at')::text BETWEEN $1 AND $2
        """,
        ws, we,
    )

    # Open threads created this week vs resolved
    open_threads = await db.fetchval(
        "SELECT COUNT(*) FROM thought_threads WHERE status = 'open'"
    )

    return {
        "week": f"{ws} → {we}",
        "commits_by_repo": [{"repo": r["repo"], "count": r["cnt"]} for r in commits_by_repo],
        "goals": [{"label": g["label"], "area": g["area"], "progress": g["progress"]} for g in goals],
        "tasks_completed_this_week": int(tasks[0]["cnt"] if tasks else 0),
        "open_threads": int(open_threads or 0),
    }


async def _monthly_metrics(period_start: date, period_end: date) -> dict[str, Any]:
    """Monthly life momentum: aggregate goal progress + cognitive load trend."""
    ps, pe = period_start.isoformat(), period_end.isoformat()

    # Total commits
    commit_count = await db.fetchval(
        """
        SELECT COUNT(*) FROM kg_nodes
        WHERE node_type = 'git_commit'
          AND (properties->>'date')::text BETWEEN $1 AND $2
        """,
        ps, pe,
    )

    # Tasks completed
    task_count = await db.fetchval(
        """
        SELECT COUNT(*) FROM kg_nodes
        WHERE node_type = 'orbit_task'
          AND (properties->>'completed_at')::text BETWEEN $1 AND $2
        """,
        ps, pe,
    )

    # Average cognitive load
    avg_load = await db.fetchval(
        """
        SELECT AVG(debt_score) FROM cognitive_load_samples
        WHERE sampled_at BETWEEN $1 AND $2
        """,
        period_start, period_end,
    )

    # Goals at different progress levels
    goals_data = await db.fetch(
        """
        SELECT
            COUNT(*) FILTER (WHERE (properties->>'progress')::float >= 80) as near_done,
            COUNT(*) FILTER (WHERE (properties->>'progress')::float BETWEEN 40 AND 79) as on_track,
            COUNT(*) FILTER (WHERE (properties->>'progress')::float < 40) as behind
        FROM kg_nodes WHERE node_type = 'orbit_goal'
        """,
    )

    goal_summary = {"near_done": 0, "on_track": 0, "behind": 0}
    if goals_data:
        row = goals_data[0]
        goal_summary = {
            "near_done": int(row["near_done"] or 0),
            "on_track": int(row["on_track"] or 0),
            "behind": int(row["behind"] or 0),
        }

    return {
        "month": f"{period_start.year}-{period_start.month:02d}",
        "commits": int(commit_count or 0),
        "tasks_completed": int(task_count or 0),
        "avg_cognitive_load": round(float(avg_load or 0), 1),
        "goal_summary": goal_summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM generation
# ─────────────────────────────────────────────────────────────────────────────

_PROMPTS = {
    "daily": (
        "Vergleiche geplante Aktivitäten (Orbit-Tasks) mit den tatsächlich erledigten "
        "(Git-Commits, Kalender). Was wurde erreicht? Was blieb offen? "
        "Gib 1–2 Handlungsempfehlungen für morgen."
    ),
    "weekly": (
        "Analysiere die Projektzeitverteilung diese Woche. Stimmt die Arbeit mit den "
        "langfristigen Zielen (Life Areas) überein? Erkenne Drift und benenne konkrete "
        "Anpassungen für nächste Woche (Drift-Detektor)."
    ),
    "monthly": (
        "Bewerte den monatlichen Fortschritt. Berechne einen 'Life Momentum Score' (0–100) "
        "basierend auf Zielfortschritt, erledigten Tasks und kognitivem Belastungsgrad. "
        "Beantworte: Bist du noch auf Kurs für das Jahresziel?"
    ),
}


async def _generate(period_type: str, metrics: dict[str, Any]) -> str:
    prompt = _PROMPTS.get(period_type, "Erstelle einen Reflexionsbericht.")
    user_msg = f"Daten:\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n{prompt}"
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_REFLECTION},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 500,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
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
        logger.warning("reflection_llm_failed period=%s error=%s", period_type, exc)

    return f"[Reflexion {period_type} — LLM nicht verfügbar]\n{json.dumps(metrics, ensure_ascii=False)}"


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

async def _save(
    period_type: str,
    period_start: date,
    period_end: date,
    content: str,
    metrics: dict[str, Any],
) -> ReflectionReport:
    row = await db.fetchrow(
        """
        INSERT INTO reflection_reports (period_type, period_start, period_end, content, metrics)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (period_type, period_start) DO UPDATE
            SET content = EXCLUDED.content,
                metrics = EXCLUDED.metrics,
                generated_at = NOW()
        RETURNING *
        """,
        period_type, period_start, period_end, content, metrics,
    )
    if row:
        return _row_to_report(row)
    return ReflectionReport(
        id=uuid.uuid4(),
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        content=content,
        metrics=metrics,
        generated_at=datetime.now(timezone.utc),
    )


async def _load_cached(
    period_type: str,
    period_start: date,
    period_end: date,
) -> Optional[ReflectionReport]:
    row = await db.fetchrow(
        "SELECT * FROM reflection_reports WHERE period_type = $1 AND period_start = $2",
        period_type, period_start,
    )
    return _row_to_report(row) if row else None


def _row_to_report(row: Any) -> ReflectionReport:
    return ReflectionReport(
        id=row["id"],
        period_type=row["period_type"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        content=row["content"],
        metrics=dict(row["metrics"]) if row["metrics"] else {},
        generated_at=row["generated_at"],
    )
