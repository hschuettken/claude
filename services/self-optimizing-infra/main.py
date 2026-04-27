"""Self-Optimizing Infrastructure service — main FastAPI application.

Port: 8242

Provides:
  L0 monitor — agent health via NATS heartbeats
  L1 monitor — infra health polling (Proxmox, Bootstrap bridge, K3s)
  L2 decision engine — rule-based auto-remediation + auto-approve framework
  Infra Evolution — monthly analysis + optimization proposals
  Chaos Testing — scheduled resilience experiments + reports

NATS subjects subscribed:
  heartbeat.> — L0 service health tracking

NATS subjects published:
  infra.alert.critical — high-severity decision triggered
  infra.decision.created — new decision record
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from . import decision_engine as de
from . import evolution as evo
from . import chaos
from . import monitors
from .config import settings
from .models import (
    ChaosRun,
    ChaosRunCreate,
    Decision,
    DecisionApproveRequest,
    DecisionRejectRequest,
    DecisionRule,
    DecisionRuleCreate,
    EvolutionProposal,
    EvolutionProposalResolve,
    EvolutionReport,
    ResilienceReport,
    ServiceHealth,
    SoiDashboard,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_nats: Optional[Any] = None
_background_tasks: list[asyncio.Task] = []


# ─────────────────────────────────────────────────────────────────────────────
# NATS
# ─────────────────────────────────────────────────────────────────────────────

async def _start_nats() -> None:
    global _nats
    try:
        from shared.nats_client import NatsPublisher  # type: ignore[import]
        _nats = NatsPublisher(url=settings.nats_url)
        await _nats.connect()
        # Subscribe to all homelab service heartbeats (L0 monitor)
        await _nats.subscribe_json(
            "heartbeat.>",
            _on_heartbeat,
        )
        logger.info("soi nats_connected heartbeat_sub=heartbeat.>")
    except Exception as exc:
        logger.warning("soi nats_unavailable error=%s — L0 monitoring degraded", exc)
        _nats = None


def _on_heartbeat(payload: dict[str, Any], subject: str = "") -> None:
    """Extract service name from NATS subject and update L0 health."""
    # Subject format: heartbeat.<service-name>
    parts = subject.split(".", 1)
    service_name = parts[1] if len(parts) == 2 else payload.get("service", "unknown")
    monitors.on_heartbeat(service_name, payload)


async def _publish_nats(subject: str, payload: dict[str, Any]) -> None:
    if _nats is None:
        return
    try:
        await _nats.publish(subject, json.dumps(payload).encode())
    except Exception as exc:
        logger.debug("soi nats_publish_failed subject=%s error=%s", subject, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Background loops
# ─────────────────────────────────────────────────────────────────────────────

async def _decision_loop() -> None:
    """Evaluate decision rules every `decision_loop_interval_seconds`."""
    await asyncio.sleep(30)  # Warm-up: let L1 poll complete first
    while True:
        try:
            snapshot = monitors.get_infra_snapshot()
            new_decisions = await de.evaluate_rules(snapshot)
            for d in new_decisions:
                await _publish_nats("infra.decision.created", {
                    "decision_id": str(d.id),
                    "rule_name": d.rule_name,
                    "action_type": d.action_type,
                    "risk_level": d.risk_level,
                    "auto_approved": d.auto_approved,
                })
                if d.risk_level == "high" and not d.auto_approved:
                    await _publish_nats("infra.alert.critical", {
                        "decision_id": str(d.id),
                        "rule_name": d.rule_name,
                        "action_type": d.action_type,
                        "trigger": d.trigger_data,
                    })
        except Exception as exc:
            logger.warning("soi decision_loop_error error=%s", exc)
        await asyncio.sleep(settings.decision_loop_interval_seconds)


async def _l1_poll_loop() -> None:
    """Poll L1 infra sources every `l1_poll_interval_seconds`."""
    while True:
        try:
            nodes = await monitors.run_l1_poll()
            logger.debug("soi l1_poll_done nodes=%d", len(nodes))
        except Exception as exc:
            logger.warning("soi l1_poll_error error=%s", exc)
        await asyncio.sleep(settings.l1_poll_interval_seconds)


async def _evolution_scheduler_loop() -> None:
    """Run the monthly evolution analysis on the configured day of month."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.day == settings.evolution_day_of_month and now.hour == 4:
                await evo.run_evolution_analysis()
        except Exception as exc:
            logger.warning("soi evolution_loop_error error=%s", exc)
        # Check once per hour
        await asyncio.sleep(3600)


async def _chaos_scheduler_loop() -> None:
    """Run chaos sweep on configured cron schedule (Sunday 03:00 by default).

    Uses simple day-of-week + hour check rather than a full cron parser.
    """
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Default cron: 0 3 * * 0 (Sunday 03:00)
            if settings.chaos_schedule_cron == "0 3 * * 0":
                if now.weekday() == 6 and now.hour == 3 and now.minute < 2:
                    logger.info("soi chaos_sweep_scheduled starting")
                    await chaos.run_chaos_sweep()
        except Exception as exc:
            logger.warning("soi chaos_loop_error error=%s", exc)
        await asyncio.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    await _start_nats()
    await de.seed_default_rules()
    await de.resume_approved_decisions()

    _background_tasks.extend([
        asyncio.create_task(_l1_poll_loop()),
        asyncio.create_task(_decision_loop()),
        asyncio.create_task(_evolution_scheduler_loop()),
        asyncio.create_task(_chaos_scheduler_loop()),
        asyncio.create_task(_register_with_oracle()),
    ])

    logger.info("soi_started port=%d", settings.port)
    yield

    for t in _background_tasks:
        t.cancel()
    if _nats is not None:
        await _nats.close()
    await db.close_pool()
    logger.info("soi_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Self-Optimizing Infrastructure",
    description=(
        "L0/L1/L2 monitoring, decision engine with auto-approve, "
        "infra evolution proposals, and chaos resilience testing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    pool_ok = db.get_pool() is not None
    return {
        "status": "ok" if pool_ok else "degraded",
        "db": "connected" if pool_ok else "unavailable",
        "nats": "connected" if (_nats and getattr(_nats, "connected", False)) else "disconnected",
    }


# ─────────────────────────────────────────────────────────────────────────────
# L0 / L1 Monitor endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/monitors/services", response_model=list[ServiceHealth])
async def list_service_health():
    """L0: All tracked homelab service heartbeat statuses."""
    return monitors.get_l0_services()


@app.get("/api/v1/monitors/nodes")
async def list_node_health():
    """L1: All tracked infra node statuses (Proxmox, Bootstrap, K3s)."""
    return [n.model_dump() for n in monitors.get_l1_nodes()]


@app.get("/api/v1/monitors/snapshot")
async def get_infra_snapshot():
    """L2: Unified infra snapshot used by the decision engine."""
    return monitors.get_infra_snapshot()


@app.post("/api/v1/monitors/poll", status_code=202)
async def trigger_l1_poll():
    """Manually trigger an L1 poll of all infra sources."""
    asyncio.create_task(monitors.run_l1_poll())
    return {"status": "poll_triggered"}


# ─────────────────────────────────────────────────────────────────────────────
# Decision Engine — Rules
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/decisions/rules", response_model=list[DecisionRule])
async def list_rules(enabled_only: bool = Query(False)):
    return await de.list_rules(enabled_only=enabled_only)


@app.post("/api/v1/decisions/rules", response_model=DecisionRule, status_code=201)
async def create_rule(data: DecisionRuleCreate):
    rule = await de.create_rule(data)
    if not rule:
        raise HTTPException(503, "Database unavailable")
    return rule


@app.get("/api/v1/decisions/rules/{rule_id}", response_model=DecisionRule)
async def get_rule(rule_id: uuid.UUID):
    rule = await de.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


@app.post("/api/v1/decisions/rules/{rule_id}/enable", response_model=DecisionRule)
async def enable_rule(rule_id: uuid.UUID):
    rule = await de.toggle_rule(rule_id, True)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


@app.post("/api/v1/decisions/rules/{rule_id}/disable", response_model=DecisionRule)
async def disable_rule(rule_id: uuid.UUID):
    rule = await de.toggle_rule(rule_id, False)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


# ─────────────────────────────────────────────────────────────────────────────
# Decision Engine — Decisions
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/decisions", response_model=list[Decision])
async def list_decisions(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await de.list_decisions(status=status, limit=limit, offset=offset)


@app.get("/api/v1/decisions/{decision_id}", response_model=Decision)
async def get_decision(decision_id: uuid.UUID):
    d = await de.get_decision(decision_id)
    if not d:
        raise HTTPException(404, "Decision not found")
    return d


@app.post("/api/v1/decisions/{decision_id}/approve", response_model=Decision)
async def approve_decision(decision_id: uuid.UUID, req: DecisionApproveRequest):
    d = await de.approve_decision(decision_id, req.approved_by)
    if not d:
        raise HTTPException(409, "Decision not in 'pending' state or not found")
    asyncio.create_task(de._execute_decision(d))
    return d


@app.post("/api/v1/decisions/{decision_id}/reject", response_model=Decision)
async def reject_decision(decision_id: uuid.UUID, req: DecisionRejectRequest):
    d = await de.reject_decision(decision_id, req.rejected_by, req.reason)
    if not d:
        raise HTTPException(409, "Decision not in pending/approved state or not found")
    return d


@app.post("/api/v1/decisions/evaluate", status_code=202)
async def trigger_evaluation():
    """Manually trigger one decision engine evaluation cycle."""
    snapshot = monitors.get_infra_snapshot()
    asyncio.create_task(de.evaluate_rules(snapshot))
    return {"status": "evaluation_triggered"}


# ─────────────────────────────────────────────────────────────────────────────
# Infra Evolution
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/evolution/proposals", response_model=list[EvolutionProposal])
async def list_proposals(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await evo.list_proposals(status=status, limit=limit, offset=offset)


@app.get("/api/v1/evolution/proposals/{proposal_id}", response_model=EvolutionProposal)
async def get_proposal(proposal_id: uuid.UUID):
    p = await evo.get_proposal(proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found")
    return p


@app.post("/api/v1/evolution/proposals/{proposal_id}/approve", response_model=EvolutionProposal)
async def approve_proposal(proposal_id: uuid.UUID, req: EvolutionProposalResolve):
    p = await evo.approve_proposal(proposal_id, req.resolved_by, req.reason)
    if not p:
        raise HTTPException(409, "Proposal not in 'pending' state or not found")
    return p


@app.post("/api/v1/evolution/proposals/{proposal_id}/reject", response_model=EvolutionProposal)
async def reject_proposal(proposal_id: uuid.UUID, req: EvolutionProposalResolve):
    p = await evo.reject_proposal(proposal_id, req.resolved_by, req.reason)
    if not p:
        raise HTTPException(409, "Proposal not in 'pending' state or not found")
    return p


@app.post("/api/v1/evolution/proposals/{proposal_id}/implement", response_model=EvolutionProposal)
async def implement_proposal(proposal_id: uuid.UUID, req: EvolutionProposalResolve):
    p = await evo.mark_implemented(proposal_id, req.resolved_by)
    if not p:
        raise HTTPException(409, "Proposal not in 'approved' state or not found")
    return p


@app.post("/api/v1/evolution/analyze", status_code=202)
async def trigger_analysis(period_days: int = Query(30, ge=7, le=365)):
    """Manually trigger a full infra evolution analysis."""
    asyncio.create_task(evo.run_evolution_analysis(period_days))
    return {"status": "analysis_triggered", "period_days": period_days}


@app.get("/api/v1/evolution/report")
async def get_evolution_report(period_days: int = Query(30, ge=7, le=365)):
    """Generate and return an evolution report synchronously."""
    report = await evo.run_evolution_analysis(period_days)
    return report.model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Chaos Testing
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/chaos/runs", response_model=list[ChaosRun])
async def list_chaos_runs(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await chaos.list_runs(limit=limit, offset=offset)


@app.get("/api/v1/chaos/runs/{run_id}", response_model=ChaosRun)
async def get_chaos_run(run_id: uuid.UUID):
    run = await chaos.get_run(run_id)
    if not run:
        raise HTTPException(404, "Chaos run not found")
    return run


@app.post("/api/v1/chaos/runs", response_model=ChaosRun, status_code=201)
async def start_chaos_run(data: ChaosRunCreate):
    """Manually trigger a chaos experiment on a specific target."""
    run = await chaos.create_run(data)
    if not run:
        raise HTTPException(503, "Database unavailable")
    asyncio.create_task(chaos.execute_experiment(run))
    return run


@app.post("/api/v1/chaos/sweep", status_code=202)
async def trigger_chaos_sweep():
    """Manually trigger a chaos sweep across a random sample of services."""
    asyncio.create_task(chaos.run_chaos_sweep())
    return {"status": "chaos_sweep_triggered", "chaos_enabled": settings.chaos_enabled}


@app.get("/api/v1/chaos/resilience-report")
async def get_resilience_report(limit: int = Query(50, le=200)):
    report = await chaos.generate_resilience_report(limit=limit)
    return report.model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/dashboard", response_model=SoiDashboard)
async def dashboard():
    services = monitors.get_l0_services()
    nodes = monitors.get_l1_nodes()
    open_decisions = await db.fetchval(
        "SELECT COUNT(*) FROM soi_decisions WHERE status IN ('pending', 'approved')"
    )
    auto_today = await db.fetchval(
        "SELECT COUNT(*) FROM soi_decisions WHERE auto_approved=true AND created_at >= NOW() - INTERVAL '24 hours'"
    )
    open_proposals = await db.fetchval(
        "SELECT COUNT(*) FROM soi_evolution_proposals WHERE status='pending'"
    )
    last_chaos_row = await db.fetchrow(
        "SELECT started_at FROM soi_chaos_runs ORDER BY started_at DESC LIMIT 1"
    )
    score_row = await db.fetchrow(
        """
        SELECT
            SUM(CASE WHEN status='passed' THEN 1 ELSE 0 END)::float
            / NULLIF(COUNT(*), 0) AS score
        FROM soi_chaos_runs
        """
    )
    return SoiDashboard(
        services_online=sum(1 for s in services if s.status == "online"),
        services_offline=sum(1 for s in services if s.status != "online"),
        nodes_online=sum(1 for n in nodes if n.status == "online"),
        nodes_offline=sum(1 for n in nodes if n.status != "online"),
        open_decisions=int(open_decisions or 0),
        auto_approved_today=int(auto_today or 0),
        open_proposals=int(open_proposals or 0),
        last_chaos_run=last_chaos_row["started_at"] if last_chaos_row else None,
        chaos_resilience_score=float(score_row["score"]) if score_row and score_row["score"] else None,
        decision_engine_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Oracle registration
# ─────────────────────────────────────────────────────────────────────────────

async def _register_with_oracle() -> None:
    manifest = {
        "service_name": "self-optimizing-infra",
        "port": settings.port,
        "description": (
            "L0/L1/L2 infra monitoring, rule-based decision engine with auto-approve, "
            "monthly evolution proposals, and chaos resilience testing."
        ),
        "endpoints": [
            {"method": "GET",  "path": "/health",                                     "purpose": "Health check"},
            {"method": "GET",  "path": "/api/v1/monitors/services",                   "purpose": "L0 service heartbeat statuses"},
            {"method": "GET",  "path": "/api/v1/monitors/nodes",                      "purpose": "L1 infra node statuses"},
            {"method": "GET",  "path": "/api/v1/monitors/snapshot",                   "purpose": "L2 unified infra snapshot"},
            {"method": "POST", "path": "/api/v1/monitors/poll",                       "purpose": "Trigger L1 poll"},
            {"method": "GET",  "path": "/api/v1/decisions/rules",                     "purpose": "List decision rules"},
            {"method": "POST", "path": "/api/v1/decisions/rules",                     "purpose": "Create decision rule"},
            {"method": "GET",  "path": "/api/v1/decisions/rules/{id}",                "purpose": "Get rule"},
            {"method": "POST", "path": "/api/v1/decisions/rules/{id}/enable",         "purpose": "Enable rule"},
            {"method": "POST", "path": "/api/v1/decisions/rules/{id}/disable",        "purpose": "Disable rule"},
            {"method": "GET",  "path": "/api/v1/decisions",                           "purpose": "List decisions"},
            {"method": "GET",  "path": "/api/v1/decisions/{id}",                      "purpose": "Get decision"},
            {"method": "POST", "path": "/api/v1/decisions/{id}/approve",              "purpose": "Approve decision (human)"},
            {"method": "POST", "path": "/api/v1/decisions/{id}/reject",               "purpose": "Reject decision"},
            {"method": "POST", "path": "/api/v1/decisions/evaluate",                  "purpose": "Trigger evaluation cycle"},
            {"method": "GET",  "path": "/api/v1/evolution/proposals",                 "purpose": "List evolution proposals"},
            {"method": "GET",  "path": "/api/v1/evolution/proposals/{id}",             "purpose": "Get proposal"},
            {"method": "POST", "path": "/api/v1/evolution/proposals/{id}/approve",    "purpose": "Approve proposal"},
            {"method": "POST", "path": "/api/v1/evolution/proposals/{id}/reject",     "purpose": "Reject proposal"},
            {"method": "POST", "path": "/api/v1/evolution/proposals/{id}/implement",  "purpose": "Mark implemented"},
            {"method": "POST", "path": "/api/v1/evolution/analyze",                   "purpose": "Trigger evolution analysis"},
            {"method": "GET",  "path": "/api/v1/evolution/report",                    "purpose": "Get evolution report"},
            {"method": "GET",  "path": "/api/v1/chaos/runs",                          "purpose": "List chaos runs"},
            {"method": "GET",  "path": "/api/v1/chaos/runs/{id}",                     "purpose": "Get chaos run"},
            {"method": "POST", "path": "/api/v1/chaos/runs",                          "purpose": "Start chaos experiment"},
            {"method": "POST", "path": "/api/v1/chaos/sweep",                         "purpose": "Trigger chaos sweep"},
            {"method": "GET",  "path": "/api/v1/chaos/resilience-report",             "purpose": "Resilience report"},
            {"method": "GET",  "path": "/api/v1/dashboard",                           "purpose": "Aggregated dashboard"},
        ],
        "nats_subjects": [
            {"subject": "heartbeat.>",          "direction": "subscribe", "purpose": "L0 service health tracking"},
            {"subject": "infra.alert.critical",  "direction": "publish",   "purpose": "High-risk decision triggered"},
            {"subject": "infra.decision.created","direction": "publish",   "purpose": "New decision record"},
        ],
        "source_paths": [{"repo": "claude", "paths": ["services/self-optimizing-infra/"]}],
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{settings.oracle_url}/oracle/register", json=manifest)
        logger.info("soi oracle_registered")
    except Exception as exc:
        logger.warning("soi oracle_registration_failed error=%s", exc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("self_optimizing_infra.main:app", host="0.0.0.0", port=settings.port, reload=False)
