"""Task Broker — create/claim/complete/fail tasks + NATS event dispatch."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from .models import Task, TaskClaimRequest, TaskCompleteRequest, TaskCreate, TaskFailRequest

logger = logging.getLogger(__name__)


def _row_to_task(row: Any) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        task_type=row["task_type"],
        status=row["status"],
        priority=row["priority"],
        assigned_to=row["assigned_to"],
        created_by=row["created_by"],
        nats_subject=row["nats_subject"],
        nats_payload=dict(row["nats_payload"] or {}),
        budget_tokens_max=row["budget_tokens_max"],
        tokens_used=row["tokens_used"],
        quality_score=row["quality_score"],
        result=dict(row["result"]) if row["result"] else None,
        error=row["error"],
        claimed_at=row["claimed_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_task(data: TaskCreate) -> Optional[Task]:
    row = await db.fetchrow(
        """
        INSERT INTO ae_tasks
            (title, description, task_type, priority, created_by, nats_subject, nats_payload, budget_tokens_max)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        data.title,
        data.description,
        data.task_type,
        data.priority,
        data.created_by,
        data.nats_subject,
        data.nats_payload,
        data.budget_tokens_max,
    )
    return _row_to_task(row) if row else None


async def get_task(task_id: uuid.UUID) -> Optional[Task]:
    row = await db.fetchrow("SELECT * FROM ae_tasks WHERE id = $1", task_id)
    return _row_to_task(row) if row else None


async def list_tasks(
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    assigned_to: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    conditions = []
    params: list[Any] = []
    idx = 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if task_type:
        conditions.append(f"task_type = ${idx}")
        params.append(task_type)
        idx += 1
    if assigned_to:
        conditions.append(f"assigned_to = ${idx}")
        params.append(assigned_to)
        idx += 1
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    rows = await db.fetch(
        f"SELECT * FROM ae_tasks {where} ORDER BY priority DESC, created_at ASC LIMIT ${idx} OFFSET ${idx+1}",
        *params,
    )
    return [_row_to_task(r) for r in rows]


async def claim_task(task_id: uuid.UUID, req: TaskClaimRequest) -> Optional[Task]:
    """Atomically claim a task — fails if already claimed."""
    row = await db.fetchrow(
        """
        UPDATE ae_tasks
        SET status = 'claimed', assigned_to = $1, claimed_at = NOW(), updated_at = NOW()
        WHERE id = $2 AND status = 'created'
        RETURNING *
        """,
        req.agent_id,
        task_id,
    )
    if row:
        await db.execute(
            "UPDATE ae_agents SET status = 'busy', updated_at = NOW() WHERE id = $1",
            req.agent_id,
        )
    return _row_to_task(row) if row else None


async def complete_task(task_id: uuid.UUID, req: TaskCompleteRequest) -> Optional[Task]:
    row = await db.fetchrow(
        """
        UPDATE ae_tasks
        SET status = 'completed', result = $1, tokens_used = $2, quality_score = $3,
            completed_at = NOW(), updated_at = NOW()
        WHERE id = $4 AND status = 'claimed'
        RETURNING *
        """,
        req.result,
        req.tokens_used,
        req.quality_score,
        task_id,
    )
    if row and row["assigned_to"]:
        agent_id = row["assigned_to"]
        await _update_agent_on_complete(agent_id, req.tokens_used, req.quality_score)
    return _row_to_task(row) if row else None


async def fail_task(task_id: uuid.UUID, req: TaskFailRequest) -> Optional[Task]:
    row = await db.fetchrow(
        """
        UPDATE ae_tasks
        SET status = 'failed', error = $1, tokens_used = $2, completed_at = NOW(), updated_at = NOW()
        WHERE id = $3 AND status = 'claimed'
        RETURNING *
        """,
        req.error,
        req.tokens_used,
        task_id,
    )
    if row and row["assigned_to"]:
        agent_id = row["assigned_to"]
        await _update_agent_on_fail(agent_id, req.tokens_used)
    return _row_to_task(row) if row else None


async def _update_agent_on_complete(agent_id: uuid.UUID, tokens_used: int, quality_score: float) -> None:
    """Update agent counters + reputation on task completion."""
    await db.execute(
        """
        UPDATE ae_agents
        SET tasks_completed = tasks_completed + 1,
            budget_tokens_used = budget_tokens_used + $1,
            reputation_score = LEAST(1.0,
                (reputation_score * tasks_completed + $2) / (tasks_completed + 1)
            ),
            status = 'active',
            updated_at = NOW()
        WHERE id = $3
        """,
        tokens_used,
        quality_score,
        agent_id,
    )


async def _update_agent_on_fail(agent_id: uuid.UUID, tokens_used: int) -> None:
    """Update agent counters + reputation on task failure."""
    await db.execute(
        """
        UPDATE ae_agents
        SET tasks_failed = tasks_failed + 1,
            budget_tokens_used = budget_tokens_used + $1,
            reputation_score = GREATEST(0.0,
                reputation_score * 0.95
            ),
            status = 'active',
            updated_at = NOW()
        WHERE id = $2
        """,
        tokens_used,
        agent_id,
    )


async def find_available_agent(task_type: str) -> Optional[uuid.UUID]:
    """Find the highest-reputation active agent that can handle this task type."""
    row = await db.fetchrow(
        """
        SELECT id FROM ae_agents
        WHERE status = 'active'
          AND $1 = ANY(capabilities)
          AND (budget_tokens_total = 0 OR budget_tokens_used < budget_tokens_total)
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY reputation_score DESC, tasks_completed DESC
        LIMIT 1
        """,
        task_type,
    )
    return row["id"] if row else None
