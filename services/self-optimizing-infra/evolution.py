"""Phase 2 — Infra Evolution: monthly utilization analysis + proposal generation.

Runs automatically on the configured day of month (default: 1st).
Analyzes L0/L1 health data, generates optimization proposals, stores them
in PostgreSQL, and exposes them via REST for human review + approve/reject.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from . import db
from .config import settings
from .models import (
    EvolutionProposal,
    EvolutionProposalCreate,
    EvolutionProposalResolve,
    EvolutionReport,
)
from .monitors import get_l0_services, get_l1_nodes

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_proposal(data: EvolutionProposalCreate) -> Optional[EvolutionProposal]:
    row = await db.fetchrow(
        """
        INSERT INTO soi_evolution_proposals
            (title, description, proposal_type, resource_target,
             estimated_impact, data_summary)
        VALUES ($1,$2,$3,$4,$5,$6)
        RETURNING *
        """,
        data.title, data.description, data.proposal_type, data.resource_target,
        json.dumps(data.estimated_impact), json.dumps(data.data_summary),
    )
    return _row_to_proposal(row) if row else None


async def list_proposals(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EvolutionProposal]:
    if status:
        rows = await db.fetch(
            "SELECT * FROM soi_evolution_proposals WHERE status=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            status, limit, offset,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM soi_evolution_proposals ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
    return [_row_to_proposal(r) for r in rows]


async def get_proposal(proposal_id: uuid.UUID) -> Optional[EvolutionProposal]:
    row = await db.fetchrow("SELECT * FROM soi_evolution_proposals WHERE id=$1", proposal_id)
    return _row_to_proposal(row) if row else None


async def approve_proposal(
    proposal_id: uuid.UUID, resolved_by: str, reason: str = ""
) -> Optional[EvolutionProposal]:
    row = await db.fetchrow(
        """
        UPDATE soi_evolution_proposals
        SET status='approved', resolved_at=NOW(), resolved_by=$1
        WHERE id=$2 AND status='pending'
        RETURNING *
        """,
        f"{resolved_by}: {reason}" if reason else resolved_by,
        proposal_id,
    )
    return _row_to_proposal(row) if row else None


async def reject_proposal(
    proposal_id: uuid.UUID, resolved_by: str, reason: str = ""
) -> Optional[EvolutionProposal]:
    row = await db.fetchrow(
        """
        UPDATE soi_evolution_proposals
        SET status='rejected', resolved_at=NOW(), resolved_by=$1
        WHERE id=$2 AND status='pending'
        RETURNING *
        """,
        f"{resolved_by}: {reason}" if reason else resolved_by,
        proposal_id,
    )
    return _row_to_proposal(row) if row else None


async def mark_implemented(
    proposal_id: uuid.UUID, resolved_by: str
) -> Optional[EvolutionProposal]:
    row = await db.fetchrow(
        """
        UPDATE soi_evolution_proposals
        SET status='implemented', resolved_at=NOW(), resolved_by=$1
        WHERE id=$2 AND status='approved'
        RETURNING *
        """,
        resolved_by, proposal_id,
    )
    return _row_to_proposal(row) if row else None


def _row_to_proposal(row: Any) -> EvolutionProposal:
    return EvolutionProposal(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        proposal_type=row["proposal_type"],
        resource_target=row["resource_target"],
        estimated_impact=row["estimated_impact"] if isinstance(row["estimated_impact"], dict)
                         else json.loads(row["estimated_impact"] or "{}"),
        data_summary=row["data_summary"] if isinstance(row["data_summary"], dict)
                     else json.loads(row["data_summary"] or "{}"),
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────────────────────

async def _collect_service_uptime(days: int = 30) -> dict[str, float]:
    """Estimate uptime % per service from the health table.

    Uses ratio of online snapshots to total over the analysis window.
    When the table has sparse data we fall back to current live status.
    """
    rows = await db.fetch(
        """
        SELECT service_name, status
        FROM soi_service_health
        WHERE monitor_level = 'L0'
        """
    )
    # Build from live in-memory state if DB has no data
    if not rows:
        live = get_l0_services()
        return {s.service_name: 100.0 if s.status == "online" else 0.0 for s in live}

    from collections import defaultdict
    totals: dict[str, list] = defaultdict(list)
    for row in rows:
        totals[row["service_name"]].append(1 if row["status"] == "online" else 0)

    return {
        name: round(sum(vals) / max(len(vals), 1) * 100, 1)
        for name, vals in totals.items()
    }


def _collect_node_utilization() -> dict[str, dict[str, float]]:
    """Snapshot current L1 node utilization for the report."""
    result: dict[str, dict[str, float]] = {}
    for node in get_l1_nodes():
        result[node.node_name] = {
            "cpu_pct": node.cpu_percent or 0.0,
            "mem_pct": node.mem_percent or 0.0,
            "disk_pct": node.disk_percent or 0.0,
            "status": node.status,
            "source": node.source,
        }
    return result


def _generate_proposals(
    uptime_summary: dict[str, float],
    node_util: dict[str, dict[str, float]],
) -> list[EvolutionProposalCreate]:
    """Apply heuristic rules to generate evolution proposals."""
    proposals: list[EvolutionProposalCreate] = []

    # Services with poor uptime → investigate container restart policy
    for svc, uptime_pct in uptime_summary.items():
        if uptime_pct < 95.0:
            proposals.append(EvolutionProposalCreate(
                title=f"Improve reliability of {svc} (uptime {uptime_pct:.1f}%)",
                description=(
                    f"Service '{svc}' had {uptime_pct:.1f}% uptime in the analysis window. "
                    "Consider reviewing crash logs, adding resource limits, or enabling "
                    "automatic restart with exponential back-off."
                ),
                proposal_type="improve_reliability",
                resource_target=svc,
                estimated_impact={"uptime_gain_pct": round(99.5 - uptime_pct, 1)},
                data_summary={"current_uptime_pct": uptime_pct},
            ))

    # Nodes with sustained high CPU → vertical or horizontal scaling
    for node_name, util in node_util.items():
        if util["cpu_pct"] > 80:
            proposals.append(EvolutionProposalCreate(
                title=f"Scale CPU resources on {node_name} (currently {util['cpu_pct']:.0f}%)",
                description=(
                    f"Node '{node_name}' is running at {util['cpu_pct']:.0f}% CPU. "
                    "Recommend evaluating workload migration to an underutilized node or "
                    "adding vCPUs if this is a VM."
                ),
                proposal_type="scale_cpu",
                resource_target=node_name,
                estimated_impact={"headroom_gain_pct": round(100 - util["cpu_pct"], 1)},
                data_summary={"current_cpu_pct": util["cpu_pct"]},
            ))

        if util["mem_pct"] > 85:
            proposals.append(EvolutionProposalCreate(
                title=f"Increase memory on {node_name} (currently {util['mem_pct']:.0f}%)",
                description=(
                    f"Node '{node_name}' memory at {util['mem_pct']:.0f}%. "
                    "Add RAM or migrate memory-heavy services to a larger node."
                ),
                proposal_type="scale_memory",
                resource_target=node_name,
                estimated_impact={"headroom_gain_pct": round(100 - util["mem_pct"], 1)},
                data_summary={"current_mem_pct": util["mem_pct"]},
            ))

        if util["disk_pct"] > 80:
            proposals.append(EvolutionProposalCreate(
                title=f"Expand disk on {node_name} (currently {util['disk_pct']:.0f}%)",
                description=(
                    f"Node '{node_name}' disk at {util['disk_pct']:.0f}%. "
                    "Archive old data or provision additional storage."
                ),
                proposal_type="expand_storage",
                resource_target=node_name,
                estimated_impact={"headroom_gain_pct": round(100 - util["disk_pct"], 1)},
                data_summary={"current_disk_pct": util["disk_pct"]},
            ))

    # Nodes completely offline → investigate or decommission
    offline_nodes = [n for n, u in node_util.items() if u.get("status") == "offline"]
    for node_name in offline_nodes:
        proposals.append(EvolutionProposalCreate(
            title=f"Investigate or decommission offline node {node_name}",
            description=(
                f"Node '{node_name}' was offline during the analysis period. "
                "Either bring it back online or remove it from the cluster inventory."
            ),
            proposal_type="decommission_node",
            resource_target=node_name,
            estimated_impact={},
            data_summary={"status": "offline"},
        ))

    return proposals


async def run_evolution_analysis(analysis_period_days: int = 30) -> EvolutionReport:
    """Run the full monthly evolution analysis and persist proposals."""
    logger.info("soi evolution_analysis_started period_days=%d", analysis_period_days)

    uptime_summary = await _collect_service_uptime(analysis_period_days)
    node_util = _collect_node_utilization()

    raw_proposals = _generate_proposals(uptime_summary, node_util)

    # Deduplicate: don't create a proposal if an open one already exists for the same target+type
    existing = await list_proposals(status="pending")
    existing_keys = {(p.proposal_type, p.resource_target) for p in existing}

    created: list[EvolutionProposal] = []
    for proposal_data in raw_proposals:
        key = (proposal_data.proposal_type, proposal_data.resource_target)
        if key in existing_keys:
            logger.debug("soi skipping_duplicate_proposal type=%s target=%s", *key)
            continue
        p = await create_proposal(proposal_data)
        if p:
            created.append(p)
            existing_keys.add(key)

    all_pending = await list_proposals(status="pending")

    report = EvolutionReport(
        generated_at=datetime.now(timezone.utc),
        analysis_period_days=analysis_period_days,
        service_uptime_summary=uptime_summary,
        node_utilization_summary=node_util,
        proposals=all_pending,
        recommendations_count=len(created),
    )

    logger.info(
        "soi evolution_analysis_done new_proposals=%d total_pending=%d",
        len(created), len(all_pending),
    )
    return report
