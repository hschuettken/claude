"""Self-spawning workflow — agents can request creation of specialized sub-agents."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from . import db
from . import registry
from .config import settings
from .models import SpawnApproveRequest, SpawnRejectRequest, SpawnRequest, SpawnRequestCreate

logger = logging.getLogger(__name__)


def _row_to_spawn(row: Any) -> SpawnRequest:
    return SpawnRequest(
        id=row["id"],
        requested_by=row["requested_by"],
        template_name=row["template_name"],
        purpose=row["purpose"],
        capabilities=list(row["capabilities"] or []),
        ttl_seconds=row["ttl_seconds"],
        status=row["status"],
        approved_by=row["approved_by"],
        spawned_agent_id=row["spawned_agent_id"],
        rejection_reason=row["rejection_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_spawn_request(data: SpawnRequestCreate) -> Optional[SpawnRequest]:
    row = await db.fetchrow(
        """
        INSERT INTO ae_spawn_requests
            (requested_by, template_name, purpose, capabilities, ttl_seconds)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        data.requested_by,
        data.template_name,
        data.purpose,
        data.capabilities,
        data.ttl_seconds,
    )
    if not row:
        return None
    spawn_req = _row_to_spawn(row)

    # Count active self-spawned agents; auto-approve if below threshold
    active_spawned = await db.fetchval(
        "SELECT COUNT(*) FROM ae_agents WHERE spawned_by IS NOT NULL AND status != 'inactive'"
    ) or 0
    if int(active_spawned) < settings.spawn_auto_approve_max:
        return await _do_approve(spawn_req, approved_by="system(auto)")
    return spawn_req


async def list_spawn_requests(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SpawnRequest]:
    conditions = []
    params: list[Any] = []
    idx = 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    rows = await db.fetch(
        f"SELECT * FROM ae_spawn_requests {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params,
    )
    return [_row_to_spawn(r) for r in rows]


async def get_spawn_request(req_id: uuid.UUID) -> Optional[SpawnRequest]:
    row = await db.fetchrow("SELECT * FROM ae_spawn_requests WHERE id = $1", req_id)
    return _row_to_spawn(row) if row else None


async def approve_spawn_request(req_id: uuid.UUID, req: SpawnApproveRequest) -> Optional[SpawnRequest]:
    row = await db.fetchrow(
        "SELECT * FROM ae_spawn_requests WHERE id = $1 AND status = 'pending'",
        req_id,
    )
    if not row:
        return None
    return await _do_approve(_row_to_spawn(row), approved_by=req.approved_by)


async def _do_approve(spawn_req: SpawnRequest, approved_by: str) -> SpawnRequest:
    requester = await db.fetchrow("SELECT name FROM ae_agents WHERE id = $1", spawn_req.requested_by)
    requester_name = requester["name"] if requester else str(spawn_req.requested_by)
    agent_name = f"{spawn_req.template_name}-{str(spawn_req.id)[:8]}"
    description = f"Spawned by {requester_name}: {spawn_req.purpose}"
    agent = await registry.spawn_agent(
        name=agent_name,
        agent_type=spawn_req.template_name,
        capabilities=spawn_req.capabilities,
        description=description,
        spawned_by=spawn_req.requested_by,
        ttl_seconds=spawn_req.ttl_seconds,
    )
    spawned_id = agent.id if agent else None
    row = await db.fetchrow(
        """
        UPDATE ae_spawn_requests
        SET status = 'approved', approved_by = $1, spawned_agent_id = $2, updated_at = NOW()
        WHERE id = $3
        RETURNING *
        """,
        approved_by,
        spawned_id,
        spawn_req.id,
    )
    return _row_to_spawn(row) if row else spawn_req


async def reject_spawn_request(req_id: uuid.UUID, req: SpawnRejectRequest) -> Optional[SpawnRequest]:
    row = await db.fetchrow(
        """
        UPDATE ae_spawn_requests
        SET status = 'rejected', approved_by = $1, rejection_reason = $2, updated_at = NOW()
        WHERE id = $3 AND status = 'pending'
        RETURNING *
        """,
        req.approved_by,
        req.reason,
        req_id,
    )
    return _row_to_spawn(row) if row else None
