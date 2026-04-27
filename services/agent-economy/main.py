"""Agent Economy — Autonomous Agent Economy Service.

FastAPI service providing:
  - Agent Registry (capability / cost / reliability tracking)
  - Task Broker (created → claimed → completed/failed + NATS dispatch)
  - Budget Governance (token spend per agent)
  - Reputation Scoring (quality-weighted rolling average)
  - Self-Spawning (TTL agents + approval workflow)
  - Bifrost-style JWT auth + audit log

Port: 8240

NATS events emitted:
  task.created / task.claimed / task.completed / task.failed

NATS subjects subscribed (→ auto-create tasks):
  energy.price.spike
  travel.intent.detected
  infra.alert.critical
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .models import (
    Agent,
    AgentCreate,
    AgentStats,
    AgentUpdate,
    BudgetLogCreate,
    BudgetLogEntry,
    BudgetSummary,
    DashboardStats,
    SpawnApproveRequest,
    SpawnRejectRequest,
    SpawnRequest,
    SpawnRequestCreate,
    Task,
    TaskClaimRequest,
    TaskCompleteRequest,
    TaskCreate,
    TaskFailRequest,
    TokenRequest,
    TokenResponse,
)
from . import registry, broker, budget, spawn
from .auth import create_token, get_current_agent

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_nats = None
_nats_sub_task: Optional[asyncio.Task] = None

# ─────────────────────────────────────────────────────────────────────────────
# NATS helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _publish_task_event(event: str, task: Task) -> None:
    if _nats is None:
        return
    try:
        payload = {
            "event": event,
            "task_id": str(task.id),
            "title": task.title,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        }
        await _nats.publish(f"task.{event.split('.')[-1]}", json.dumps(payload).encode())
    except Exception as exc:
        logger.warning("nats_publish_failed event=%s error=%s", event, exc)


async def _handle_nats_event(subject: str, data: bytes) -> None:
    """Convert inbound NATS topic events into tasks automatically."""
    try:
        payload = json.loads(data) if data else {}
    except Exception:
        payload = {"raw": data.decode(errors="replace")}

    # Map subjects to task types + default priority
    subject_map = {
        "energy.price.spike":       ("energy_response", 4, "Energy price spike detected"),
        "travel.intent.detected":   ("travel_planning", 3, "Travel intent detected"),
        "infra.alert.critical":     ("infra_remediation", 5, "Critical infrastructure alert"),
    }
    meta = subject_map.get(subject)
    if not meta:
        return
    task_type, priority, title = meta
    tc = TaskCreate(
        title=title,
        description=json.dumps(payload, ensure_ascii=False)[:2000],
        task_type=task_type,
        priority=priority,
        nats_subject=subject,
        nats_payload=payload,
    )
    task = await broker.create_task(tc)
    if task:
        await _publish_task_event("task.created", task)
        # Auto-dispatch to a capable agent if one is available
        agent_id = await broker.find_available_agent(task_type)
        if agent_id:
            claimed = await broker.claim_task(task.id, TaskClaimRequest(agent_id=agent_id))
            if claimed:
                await _publish_task_event("task.claimed", claimed)
        logger.info("nats_task_created subject=%s task_id=%s", subject, task.id)


async def _start_nats() -> None:
    global _nats
    try:
        from shared.nats_client import NatsPublisher  # type: ignore[import]
        _nats = NatsPublisher(url=settings.nats_url)
        await _nats.connect()
        for subject in ("energy.price.spike", "travel.intent.detected", "infra.alert.critical"):
            await _nats.subscribe_json(
                subject,
                lambda data, subj=subject: asyncio.create_task(_handle_nats_event(subj, json.dumps(data).encode())),
            )
        logger.info("agent_economy nats_connected subjects=3")
    except Exception as exc:
        logger.warning("agent_economy nats_unavailable error=%s", exc)
        _nats = None


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    await _start_nats()
    asyncio.create_task(_register_with_oracle())
    asyncio.create_task(_expire_ttl_loop())
    logger.info("agent_economy_started port=%d", settings.port)
    yield
    if _nats is not None:
        await _nats.close()
    await db.close_pool()
    logger.info("agent_economy_stopped")


async def _expire_ttl_loop() -> None:
    """Periodically deactivate TTL-expired self-spawned agents."""
    while True:
        await asyncio.sleep(60)
        try:
            expired = await registry.expire_ttl_agents()
            if expired:
                logger.info("agent_economy ttl_expired count=%d", expired)
        except Exception as exc:
            logger.warning("agent_economy ttl_expire_error error=%s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent Economy",
    description="Autonomous Agent Economy — registry, task broker, budget, reputation, self-spawning",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Audit log middleware
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    try:
        agent_payload = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            from .auth import decode_token
            agent_payload = decode_token(auth_header[7:])
        agent_id_val = None
        agent_name = None
        if agent_payload:
            agent_id_val = agent_payload.get("sub")
            agent_name = agent_payload.get("name")
        await db.execute(
            """
            INSERT INTO ae_audit_log (agent_id, agent_name, method, path, status_code, ip_address)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uuid.UUID(agent_id_val) if agent_id_val else None,
            agent_name,
            request.method,
            request.url.path,
            response.status_code,
            request.client.host if request.client else None,
        )
    except Exception:
        pass
    return response


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
# Auth — Bifrost-style token endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/auth/token", response_model=TokenResponse)
async def get_token(req: TokenRequest):
    """Issue a JWT to an agent. In production wire req.secret to per-agent secrets in .env."""
    agent = await registry.get_agent_by_name(req.agent_name)
    if not agent:
        raise HTTPException(404, "Agent not found")
    token = create_token(str(agent.id), agent.name)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_hours=settings.jwt_expire_hours,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Agent Registry
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/agents", response_model=Agent, status_code=201)
async def create_agent(data: AgentCreate):
    agent = await registry.create_agent(data)
    if not agent:
        raise HTTPException(503, "Database unavailable")
    return agent


@app.get("/api/v1/agents", response_model=list[Agent])
async def list_agents(
    agent_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await registry.list_agents(agent_type=agent_type, status=status, limit=limit, offset=offset)


@app.get("/api/v1/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: uuid.UUID):
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@app.patch("/api/v1/agents/{agent_id}", response_model=Agent)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate):
    agent = await registry.update_agent(agent_id, data)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@app.delete("/api/v1/agents/{agent_id}", status_code=204)
async def deactivate_agent(agent_id: uuid.UUID):
    agent = await registry.deactivate_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")


@app.get("/api/v1/agents/{agent_id}/stats", response_model=AgentStats)
async def get_agent_stats(agent_id: uuid.UUID):
    stats = await registry.get_agent_stats(agent_id)
    if not stats:
        raise HTTPException(404, "Agent not found")
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Task Broker
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/tasks", response_model=Task, status_code=201)
async def create_task(data: TaskCreate):
    task = await broker.create_task(data)
    if not task:
        raise HTTPException(503, "Database unavailable")
    await _publish_task_event("task.created", task)
    return task


@app.get("/api/v1/tasks", response_model=list[Task])
async def list_tasks(
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    assigned_to: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await broker.list_tasks(
        status=status, task_type=task_type, assigned_to=assigned_to,
        limit=limit, offset=offset,
    )


@app.get("/api/v1/tasks/{task_id}", response_model=Task)
async def get_task(task_id: uuid.UUID):
    task = await broker.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.post("/api/v1/tasks/{task_id}/claim", response_model=Task)
async def claim_task(task_id: uuid.UUID, req: TaskClaimRequest):
    task = await broker.claim_task(task_id, req)
    if not task:
        raise HTTPException(409, "Task not available for claiming (already claimed or not found)")
    await _publish_task_event("task.claimed", task)
    return task


@app.post("/api/v1/tasks/{task_id}/complete", response_model=Task)
async def complete_task(task_id: uuid.UUID, req: TaskCompleteRequest):
    task = await broker.complete_task(task_id, req)
    if not task:
        raise HTTPException(409, "Task not in 'claimed' state or not found")
    await _publish_task_event("task.completed", task)
    return task


@app.post("/api/v1/tasks/{task_id}/fail", response_model=Task)
async def fail_task(task_id: uuid.UUID, req: TaskFailRequest):
    task = await broker.fail_task(task_id, req)
    if not task:
        raise HTTPException(409, "Task not in 'claimed' state or not found")
    await _publish_task_event("task.failed", task)
    return task


# ─────────────────────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/budget/log", response_model=BudgetLogEntry, status_code=201)
async def log_budget(data: BudgetLogCreate):
    entry = await budget.log_spend(data)
    if not entry:
        raise HTTPException(503, "Database unavailable")
    return entry


@app.get("/api/v1/budget/log", response_model=list[BudgetLogEntry])
async def list_budget_log(
    agent_id: Optional[uuid.UUID] = Query(None),
    task_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await budget.list_entries(agent_id=agent_id, task_id=task_id, limit=limit, offset=offset)


@app.get("/api/v1/budget/summary/{agent_id}", response_model=BudgetSummary)
async def get_budget_summary(agent_id: uuid.UUID):
    summary = await budget.get_summary(agent_id)
    if not summary:
        raise HTTPException(404, "Agent not found")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Self-Spawning
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/spawn/request", response_model=SpawnRequest, status_code=201)
async def request_spawn(data: SpawnRequestCreate):
    req = await spawn.create_spawn_request(data)
    if not req:
        raise HTTPException(503, "Database unavailable")
    return req


@app.get("/api/v1/spawn/requests", response_model=list[SpawnRequest])
async def list_spawn_requests(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await spawn.list_spawn_requests(status=status, limit=limit, offset=offset)


@app.get("/api/v1/spawn/requests/{req_id}", response_model=SpawnRequest)
async def get_spawn_request(req_id: uuid.UUID):
    req = await spawn.get_spawn_request(req_id)
    if not req:
        raise HTTPException(404, "Spawn request not found")
    return req


@app.post("/api/v1/spawn/requests/{req_id}/approve", response_model=SpawnRequest)
async def approve_spawn(req_id: uuid.UUID, req: SpawnApproveRequest):
    result = await spawn.approve_spawn_request(req_id, req)
    if not result:
        raise HTTPException(409, "Spawn request not in 'pending' state or not found")
    return result


@app.post("/api/v1/spawn/requests/{req_id}/reject", response_model=SpawnRequest)
async def reject_spawn(req_id: uuid.UUID, req: SpawnRejectRequest):
    result = await spawn.reject_spawn_request(req_id, req)
    if not result:
        raise HTTPException(409, "Spawn request not in 'pending' state or not found")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard stats
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/dashboard", response_model=DashboardStats)
async def dashboard():
    from . import db as _db

    async def _val(q: str, *args) -> int:
        v = await _db.fetchval(q, *args)
        return int(v or 0)

    total_agents = await _val("SELECT COUNT(*) FROM ae_agents")
    active_agents = await _val("SELECT COUNT(*) FROM ae_agents WHERE status = 'active'")
    busy_agents = await _val("SELECT COUNT(*) FROM ae_agents WHERE status = 'busy'")
    total_tasks = await _val("SELECT COUNT(*) FROM ae_tasks")
    tasks_created = await _val("SELECT COUNT(*) FROM ae_tasks WHERE status = 'created'")
    tasks_claimed = await _val("SELECT COUNT(*) FROM ae_tasks WHERE status = 'claimed'")
    tasks_completed = await _val("SELECT COUNT(*) FROM ae_tasks WHERE status = 'completed'")
    tasks_failed = await _val("SELECT COUNT(*) FROM ae_tasks WHERE status = 'failed'")
    avg_rep = await _db.fetchval("SELECT COALESCE(AVG(reputation_score), 1.0) FROM ae_agents WHERE status != 'inactive'")
    total_tokens = await _val("SELECT COALESCE(SUM(tokens_used), 0) FROM ae_budget_log")
    pending_spawns = await _val("SELECT COUNT(*) FROM ae_spawn_requests WHERE status = 'pending'")

    top_rows = await _db.fetch(
        "SELECT * FROM ae_agents WHERE status != 'inactive' ORDER BY reputation_score DESC LIMIT 5"
    )
    top_agents = []
    for row in top_rows:
        total = row["tasks_completed"] + row["tasks_failed"]
        sr = row["tasks_completed"] / total if total > 0 else 1.0
        br = -1 if row["budget_tokens_total"] == 0 else row["budget_tokens_total"] - row["budget_tokens_used"]
        top_agents.append(AgentStats(
            agent_id=row["id"],
            agent_name=row["name"],
            tasks_completed=row["tasks_completed"],
            tasks_failed=row["tasks_failed"],
            success_rate=round(sr, 3),
            reputation_score=row["reputation_score"],
            budget_tokens_total=row["budget_tokens_total"],
            budget_tokens_used=row["budget_tokens_used"],
            budget_remaining=br,
            tokens_this_week=0,
        ))

    return DashboardStats(
        total_agents=total_agents,
        active_agents=active_agents,
        busy_agents=busy_agents,
        total_tasks=total_tasks,
        tasks_created=tasks_created,
        tasks_claimed=tasks_claimed,
        tasks_completed=tasks_completed,
        tasks_failed=tasks_failed,
        avg_reputation_score=round(float(avg_rep or 1.0), 3),
        total_tokens_used=total_tokens,
        pending_spawn_requests=pending_spawns,
        top_agents=top_agents,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Oracle registration
# ─────────────────────────────────────────────────────────────────────────────

async def _register_with_oracle() -> None:
    manifest = {
        "service_name": "agent-economy",
        "port": settings.port,
        "description": "Autonomous Agent Economy — registry, task broker, budget governance, reputation scoring, self-spawning",
        "endpoints": [
            {"method": "GET",  "path": "/health",                               "purpose": "Health check"},
            {"method": "POST", "path": "/api/v1/auth/token",                    "purpose": "Issue JWT to agent"},
            {"method": "POST", "path": "/api/v1/agents",                        "purpose": "Register agent"},
            {"method": "GET",  "path": "/api/v1/agents",                        "purpose": "List agents"},
            {"method": "GET",  "path": "/api/v1/agents/{id}",                   "purpose": "Get agent"},
            {"method": "PATCH","path": "/api/v1/agents/{id}",                   "purpose": "Update agent"},
            {"method": "DELETE","path": "/api/v1/agents/{id}",                  "purpose": "Deactivate agent"},
            {"method": "GET",  "path": "/api/v1/agents/{id}/stats",             "purpose": "Agent stats"},
            {"method": "POST", "path": "/api/v1/tasks",                         "purpose": "Create task"},
            {"method": "GET",  "path": "/api/v1/tasks",                         "purpose": "List tasks"},
            {"method": "GET",  "path": "/api/v1/tasks/{id}",                    "purpose": "Get task"},
            {"method": "POST", "path": "/api/v1/tasks/{id}/claim",              "purpose": "Claim task"},
            {"method": "POST", "path": "/api/v1/tasks/{id}/complete",           "purpose": "Complete task"},
            {"method": "POST", "path": "/api/v1/tasks/{id}/fail",               "purpose": "Fail task"},
            {"method": "POST", "path": "/api/v1/budget/log",                    "purpose": "Log token spend"},
            {"method": "GET",  "path": "/api/v1/budget/log",                    "purpose": "List budget log"},
            {"method": "GET",  "path": "/api/v1/budget/summary/{agent_id}",     "purpose": "Budget summary"},
            {"method": "POST", "path": "/api/v1/spawn/request",                 "purpose": "Request agent spawn"},
            {"method": "GET",  "path": "/api/v1/spawn/requests",                "purpose": "List spawn requests"},
            {"method": "GET",  "path": "/api/v1/spawn/requests/{id}",           "purpose": "Get spawn request"},
            {"method": "POST", "path": "/api/v1/spawn/requests/{id}/approve",   "purpose": "Approve spawn request"},
            {"method": "POST", "path": "/api/v1/spawn/requests/{id}/reject",    "purpose": "Reject spawn request"},
            {"method": "GET",  "path": "/api/v1/dashboard",                     "purpose": "Aggregated dashboard stats"},
        ],
        "nats_subjects": [
            {"subject": "task.created",            "direction": "publish",   "purpose": "New task created"},
            {"subject": "task.claimed",            "direction": "publish",   "purpose": "Task claimed by agent"},
            {"subject": "task.completed",          "direction": "publish",   "purpose": "Task completed"},
            {"subject": "task.failed",             "direction": "publish",   "purpose": "Task failed"},
            {"subject": "energy.price.spike",      "direction": "subscribe", "purpose": "Auto-create energy_response task"},
            {"subject": "travel.intent.detected",  "direction": "subscribe", "purpose": "Auto-create travel_planning task"},
            {"subject": "infra.alert.critical",    "direction": "subscribe", "purpose": "Auto-create infra_remediation task"},
        ],
        "source_paths": [{"repo": "claude", "paths": ["services/agent-economy/"]}],
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{settings.oracle_url}/oracle/register", json=manifest)
        logger.info("agent_economy oracle_registered")
    except Exception as exc:
        logger.warning("agent_economy oracle_registration_failed error=%s", exc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
