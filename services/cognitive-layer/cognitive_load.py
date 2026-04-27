"""Cognitive Load Monitor — computes the mental-debt score (0–100).

The debt score is a composite of:
  - Open thought threads (weight 40%)
  - Overdue Orbit tasks (weight 40%)
  - Unprocessed HA events in the last 24h (weight 20%)

Score interpretation:
  0–25   → low       (clear head)
  26–50  → moderate  (normal load)
  51–75  → high      (starting to pile up)
  76–100 → critical  (cognitive overload)

A sample is taken on every call to `compute()` and persisted to
`cognitive_load_samples` for trend analysis in reflection reports.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from . import db
from .config import settings
from .models import CognitiveLoadSample, CognitiveLoadStatus

logger = logging.getLogger(__name__)


async def compute() -> CognitiveLoadStatus:
    """Compute the current mental-debt score and persist a sample."""
    open_threads = await _count_open_threads()
    overdue_tasks = await _count_overdue_tasks()
    unprocessed = await _count_unprocessed_events()

    thread_score = min(open_threads / settings.open_threads_max, 1.0) * 100
    task_score = min(overdue_tasks / settings.overdue_tasks_max, 1.0) * 100
    event_score = min(unprocessed / settings.unprocessed_events_max, 1.0) * 100

    debt_score = round(
        thread_score * settings.open_threads_weight
        + task_score * settings.overdue_tasks_weight
        + event_score * settings.unprocessed_events_weight,
        1,
    )

    breakdown = {
        "threads": round(thread_score, 1),
        "tasks": round(task_score, 1),
        "events": round(event_score, 1),
    }

    # Persist sample
    await db.execute(
        """
        INSERT INTO cognitive_load_samples
            (open_threads, overdue_tasks, unprocessed_events, debt_score, breakdown)
        VALUES ($1, $2, $3, $4, $5)
        """,
        open_threads,
        overdue_tasks,
        unprocessed,
        debt_score,
        breakdown,
    )

    label = _debt_label(debt_score)
    logger.info(
        "cognitive_load_computed score=%.1f label=%s threads=%d tasks=%d events=%d",
        debt_score, label, open_threads, overdue_tasks, unprocessed,
    )

    return CognitiveLoadStatus(
        debt_score=debt_score,
        open_threads=open_threads,
        overdue_tasks=overdue_tasks,
        unprocessed_events=unprocessed,
        breakdown=breakdown,
        label=label,
    )


async def history(limit: int = 30) -> list[CognitiveLoadSample]:
    rows = await db.fetch(
        "SELECT * FROM cognitive_load_samples ORDER BY sampled_at DESC LIMIT $1",
        limit,
    )
    return [_row_to_sample(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Component counts
# ─────────────────────────────────────────────────────────────────────────────

async def _count_open_threads() -> int:
    result = await db.fetchval(
        "SELECT COUNT(*) FROM thought_threads WHERE status = 'open'"
    )
    return int(result or 0)


async def _count_overdue_tasks() -> int:
    """Fetch overdue task count from Orbit API."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.orbit_url}/api/orbit/tasks",
                params={"status": "overdue", "limit": 1},
            )
            if resp.status_code != 200:
                return 0
            data = resp.json()
            if isinstance(data, list):
                return len(data)
            return data.get("total", 0)
    except Exception:
        return 0


async def _count_unprocessed_events() -> int:
    """Count HA event nodes created in the last 24h with no outgoing edges."""
    result = await db.fetchval(
        """
        SELECT COUNT(*) FROM kg_nodes n
        LEFT JOIN kg_edges e ON e.source_id = n.id
        WHERE n.node_type = 'ha_event'
          AND n.created_at > NOW() - INTERVAL '24 hours'
          AND e.id IS NULL
        """,
    )
    return int(result or 0)


def _debt_label(score: float) -> str:
    if score <= 25:
        return "low"
    if score <= 50:
        return "moderate"
    if score <= 75:
        return "high"
    return "critical"


def _row_to_sample(row: Any) -> CognitiveLoadSample:
    return CognitiveLoadSample(
        id=row["id"],
        sampled_at=row["sampled_at"],
        open_threads=row["open_threads"],
        overdue_tasks=row["overdue_tasks"],
        unprocessed_events=row["unprocessed_events"],
        debt_score=float(row["debt_score"]),
        breakdown=dict(row["breakdown"]) if row["breakdown"] else {},
    )
