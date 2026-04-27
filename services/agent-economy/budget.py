"""Budget tracking — log token spend per agent/task."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from . import db
from .models import BudgetLogCreate, BudgetLogEntry, BudgetSummary

logger = logging.getLogger(__name__)


def _row_to_entry(row: Any) -> BudgetLogEntry:
    return BudgetLogEntry(
        id=row["id"],
        agent_id=row["agent_id"],
        task_id=row["task_id"],
        tokens_used=row["tokens_used"],
        model_name=row["model_name"],
        operation=row["operation"],
        created_at=row["created_at"],
    )


async def log_spend(data: BudgetLogCreate) -> Optional[BudgetLogEntry]:
    row = await db.fetchrow(
        """
        INSERT INTO ae_budget_log (agent_id, task_id, tokens_used, model_name, operation)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        data.agent_id,
        data.task_id,
        data.tokens_used,
        data.model_name,
        data.operation,
    )
    if row:
        # Keep ae_agents.budget_tokens_used in sync
        await db.execute(
            "UPDATE ae_agents SET budget_tokens_used = budget_tokens_used + $1, updated_at = NOW() WHERE id = $2",
            data.tokens_used,
            data.agent_id,
        )
    return _row_to_entry(row) if row else None


async def get_summary(agent_id: uuid.UUID) -> Optional[BudgetSummary]:
    agent_row = await db.fetchrow(
        "SELECT id, name, budget_tokens_total FROM ae_agents WHERE id = $1",
        agent_id,
    )
    if not agent_row:
        return None
    agg = await db.fetchrow(
        "SELECT COALESCE(SUM(tokens_used), 0) AS total, COUNT(*) AS entries FROM ae_budget_log WHERE agent_id = $1",
        agent_id,
    )
    ops = await db.fetch(
        """
        SELECT operation, SUM(tokens_used) AS tokens
        FROM ae_budget_log
        WHERE agent_id = $1 AND operation IS NOT NULL
        GROUP BY operation
        ORDER BY tokens DESC
        LIMIT 5
        """,
        agent_id,
    )
    return BudgetSummary(
        agent_id=agent_row["id"],
        agent_name=agent_row["name"],
        total_tokens=int(agg["total"]) if agg else 0,
        budget_limit=agent_row["budget_tokens_total"],
        entries=int(agg["entries"]) if agg else 0,
        top_operations=[{"operation": r["operation"], "tokens": int(r["tokens"])} for r in ops],
    )


async def list_entries(
    agent_id: Optional[uuid.UUID] = None,
    task_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BudgetLogEntry]:
    conditions = []
    params: list[Any] = []
    idx = 1
    if agent_id:
        conditions.append(f"agent_id = ${idx}")
        params.append(agent_id)
        idx += 1
    if task_id:
        conditions.append(f"task_id = ${idx}")
        params.append(task_id)
        idx += 1
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    rows = await db.fetch(
        f"SELECT * FROM ae_budget_log {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params,
    )
    return [_row_to_entry(r) for r in rows]
