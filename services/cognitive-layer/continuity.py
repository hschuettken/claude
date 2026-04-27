"""Thought Continuity Engine — tracks unfinished threads and recurring topics.

A "thread" is an open cognitive task: a question not yet answered, a project
decision deferred, or a topic that keeps recurring in chats and meetings.

Threads are created automatically when:
  - A `thought` node is added without a LEADS_TO edge (= unresolved)
  - A concept appears in ≥ 2 distinct chat nodes within 7 days (recurring)
  - An Orbit task has been open for > 3 days without a parent goal (orphan)

Threads transition states:
  open     → dormant  : not seen for 7+ days
  dormant  → open     : newly referenced again (recurrence += 1)
  open|dormant → closed : manually closed or all node_ids resolved
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from . import db
from .models import Thread, ThreadCreate, ThreadUpdate

logger = logging.getLogger(__name__)

_DORMANT_AFTER_DAYS = 7
_RECURRING_MIN_APPEARANCES = 2


# ─────────────────────────────────────────────────────────────────────────────
# Thread CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_thread(data: ThreadCreate) -> Optional[Thread]:
    row = await db.fetchrow(
        """
        INSERT INTO thought_threads (title, summary, node_ids)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        data.title,
        data.summary,
        [str(n) for n in data.node_ids],
    )
    return _row_to_thread(row) if row else None


async def get_thread(thread_id: uuid.UUID) -> Optional[Thread]:
    row = await db.fetchrow("SELECT * FROM thought_threads WHERE id = $1", thread_id)
    return _row_to_thread(row) if row else None


async def list_threads(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Thread]:
    if status:
        rows = await db.fetch(
            "SELECT * FROM thought_threads WHERE status = $1 ORDER BY last_seen_at DESC LIMIT $2 OFFSET $3",
            status, limit, offset,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM thought_threads ORDER BY last_seen_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
    return [_row_to_thread(r) for r in rows]


async def update_thread(thread_id: uuid.UUID, data: ThreadUpdate) -> Optional[Thread]:
    sets = ["last_seen_at = NOW()"]
    args: list[Any] = []
    idx = 1
    if data.title is not None:
        sets.append(f"title = ${idx}")
        args.append(data.title)
        idx += 1
    if data.summary is not None:
        sets.append(f"summary = ${idx}")
        args.append(data.summary)
        idx += 1
    if data.status is not None:
        sets.append(f"status = ${idx}")
        args.append(data.status)
        idx += 1
    if data.node_ids is not None:
        sets.append(f"node_ids = ${idx}")
        args.append([str(n) for n in data.node_ids])
        idx += 1
    args.append(thread_id)
    row = await db.fetchrow(
        f"UPDATE thought_threads SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
        *args,
    )
    return _row_to_thread(row) if row else None


async def close_thread(thread_id: uuid.UUID) -> Optional[Thread]:
    return await update_thread(thread_id, ThreadUpdate(status="closed"))


async def touch_thread(thread_id: uuid.UUID) -> Optional[Thread]:
    """Mark thread as seen; transitions dormant → open and increments recurrence."""
    row = await db.fetchrow(
        """
        UPDATE thought_threads
        SET last_seen_at = NOW(),
            status = CASE WHEN status = 'dormant' THEN 'open' ELSE status END,
            recurrence = CASE WHEN status = 'dormant' THEN recurrence + 1 ELSE recurrence END
        WHERE id = $1
        RETURNING *
        """,
        thread_id,
    )
    return _row_to_thread(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Automatic thread maintenance
# ─────────────────────────────────────────────────────────────────────────────

async def run_maintenance() -> dict[str, int]:
    """Nightly job: mark stale threads dormant, detect recurring topics.

    Returns counts of changes made.
    """
    dormant_count = await _mark_stale_threads_dormant()
    recurring_count = await _detect_recurring_topics()
    orphan_count = await _detect_orphan_thoughts()
    logger.info(
        "thought_continuity_maintenance dormant=%d recurring=%d orphans=%d",
        dormant_count, recurring_count, orphan_count,
    )
    return {"dormant": dormant_count, "recurring": recurring_count, "orphans": orphan_count}


async def _mark_stale_threads_dormant() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_DORMANT_AFTER_DAYS)).isoformat()
    result = await db.fetchval(
        """
        WITH updated AS (
            UPDATE thought_threads
            SET status = 'dormant'
            WHERE status = 'open' AND last_seen_at < $1
            RETURNING id
        )
        SELECT COUNT(*) FROM updated
        """,
        cutoff,
    )
    return int(result or 0)


async def _detect_recurring_topics() -> int:
    """Finds concept/thought labels that appear in multiple chats recently."""
    rows = await db.fetch(
        """
        SELECT label, COUNT(*) as appearances
        FROM kg_nodes
        WHERE node_type IN ('thought', 'concept')
          AND created_at > NOW() - INTERVAL '7 days'
        GROUP BY label
        HAVING COUNT(*) >= $1
        """,
        _RECURRING_MIN_APPEARANCES,
    )
    count = 0
    for row in rows:
        existing = await db.fetchrow(
            "SELECT id FROM thought_threads WHERE title = $1 AND status != 'closed'",
            row["label"],
        )
        if existing:
            await touch_thread(existing["id"])
        else:
            await create_thread(ThreadCreate(
                title=row["label"],
                summary=f"Recurring topic — appeared {row['appearances']} times in the last 7 days",
            ))
            count += 1
    return count


async def _detect_orphan_thoughts() -> int:
    """Creates threads for thought nodes that have no LEADS_TO edge (unresolved)."""
    rows = await db.fetch(
        """
        SELECT n.id, n.label
        FROM kg_nodes n
        LEFT JOIN kg_edges e ON e.source_id = n.id AND e.relation_type = 'LEADS_TO'
        WHERE n.node_type = 'thought'
          AND e.id IS NULL
          AND n.created_at < NOW() - INTERVAL '1 day'
        LIMIT 20
        """,
    )
    count = 0
    for row in rows:
        existing = await db.fetchrow(
            "SELECT id FROM thought_threads WHERE $1 = ANY(node_ids::uuid[]) AND status != 'closed'",
            row["id"],
        )
        if not existing:
            await create_thread(ThreadCreate(
                title=f"Unresolved: {row['label']}",
                summary="Thought with no resolution edge — possible open question.",
                node_ids=[row["id"]],
            ))
            count += 1
    return count


def _row_to_thread(row: Any) -> Thread:
    raw_ids = row["node_ids"] or []
    node_ids = [uuid.UUID(str(n)) for n in raw_ids]
    return Thread(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        recurrence=row["recurrence"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
        node_ids=node_ids,
    )
