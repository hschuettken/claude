"""Agent Registry — CRUD operations for ae_agents."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from . import db
from .models import Agent, AgentCreate, AgentStats, AgentUpdate

logger = logging.getLogger(__name__)


def _row_to_agent(row: Any) -> Agent:
    return Agent(
        id=row["id"],
        name=row["name"],
        agent_type=row["agent_type"],
        capabilities=list(row["capabilities"] or []),
        description=row["description"],
        status=row["status"],
        spawned_by=row["spawned_by"],
        ttl_seconds=row["ttl_seconds"],
        expires_at=row["expires_at"],
        budget_tokens_total=row["budget_tokens_total"],
        budget_tokens_used=row["budget_tokens_used"],
        reputation_score=row["reputation_score"],
        tasks_completed=row["tasks_completed"],
        tasks_failed=row["tasks_failed"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_agent(data: AgentCreate) -> Optional[Agent]:
    row = await db.fetchrow(
        """
        INSERT INTO ae_agents (name, agent_type, capabilities, description, budget_tokens_total)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        data.name,
        data.agent_type,
        data.capabilities,
        data.description,
        data.budget_tokens_total,
    )
    return _row_to_agent(row) if row else None


async def get_agent(agent_id: uuid.UUID) -> Optional[Agent]:
    row = await db.fetchrow("SELECT * FROM ae_agents WHERE id = $1", agent_id)
    return _row_to_agent(row) if row else None


async def get_agent_by_name(name: str) -> Optional[Agent]:
    row = await db.fetchrow("SELECT * FROM ae_agents WHERE name = $1", name)
    return _row_to_agent(row) if row else None


async def list_agents(
    agent_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Agent]:
    conditions = []
    params: list[Any] = []
    idx = 1
    if agent_type:
        conditions.append(f"agent_type = ${idx}")
        params.append(agent_type)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    rows = await db.fetch(
        f"SELECT * FROM ae_agents {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params,
    )
    return [_row_to_agent(r) for r in rows]


async def update_agent(agent_id: uuid.UUID, data: AgentUpdate) -> Optional[Agent]:
    updates: list[str] = ["updated_at = NOW()"]
    params: list[Any] = []
    idx = 1
    if data.description is not None:
        updates.append(f"description = ${idx}")
        params.append(data.description)
        idx += 1
    if data.capabilities is not None:
        updates.append(f"capabilities = ${idx}")
        params.append(data.capabilities)
        idx += 1
    if data.status is not None:
        updates.append(f"status = ${idx}")
        params.append(data.status)
        idx += 1
    if data.budget_tokens_total is not None:
        updates.append(f"budget_tokens_total = ${idx}")
        params.append(data.budget_tokens_total)
        idx += 1
    params.append(agent_id)
    row = await db.fetchrow(
        f"UPDATE ae_agents SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
        *params,
    )
    return _row_to_agent(row) if row else None


async def deactivate_agent(agent_id: uuid.UUID) -> Optional[Agent]:
    row = await db.fetchrow(
        "UPDATE ae_agents SET status = 'inactive', updated_at = NOW() WHERE id = $1 RETURNING *",
        agent_id,
    )
    return _row_to_agent(row) if row else None


async def spawn_agent(
    name: str,
    agent_type: str,
    capabilities: list[str],
    description: str,
    spawned_by: uuid.UUID,
    ttl_seconds: Optional[int],
) -> Optional[Agent]:
    expires_at = None
    if ttl_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    row = await db.fetchrow(
        """
        INSERT INTO ae_agents
            (name, agent_type, capabilities, description, spawned_by, ttl_seconds, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        name,
        agent_type,
        capabilities,
        description,
        spawned_by,
        ttl_seconds,
        expires_at,
    )
    return _row_to_agent(row) if row else None


async def get_agent_stats(agent_id: uuid.UUID) -> Optional[AgentStats]:
    row = await db.fetchrow("SELECT * FROM ae_agents WHERE id = $1", agent_id)
    if not row:
        return None
    total = row["tasks_completed"] + row["tasks_failed"]
    success_rate = row["tasks_completed"] / total if total > 0 else 1.0
    tokens_week = await db.fetchval(
        """
        SELECT COALESCE(SUM(tokens_used), 0)
        FROM ae_budget_log
        WHERE agent_id = $1 AND created_at >= NOW() - INTERVAL '7 days'
        """,
        agent_id,
    ) or 0
    budget_remaining = -1
    if row["budget_tokens_total"] > 0:
        budget_remaining = row["budget_tokens_total"] - row["budget_tokens_used"]
    return AgentStats(
        agent_id=row["id"],
        agent_name=row["name"],
        tasks_completed=row["tasks_completed"],
        tasks_failed=row["tasks_failed"],
        success_rate=round(success_rate, 3),
        reputation_score=row["reputation_score"],
        budget_tokens_total=row["budget_tokens_total"],
        budget_tokens_used=row["budget_tokens_used"],
        budget_remaining=budget_remaining,
        tokens_this_week=int(tokens_week),
    )


async def expire_ttl_agents() -> int:
    """Mark TTL-based agents inactive when their expires_at has passed."""
    result = await db.fetchval(
        """
        WITH expired AS (
            UPDATE ae_agents
            SET status = 'inactive', updated_at = NOW()
            WHERE expires_at IS NOT NULL AND expires_at <= NOW() AND status != 'inactive'
            RETURNING id
        )
        SELECT COUNT(*) FROM expired
        """,
    )
    return int(result or 0)
