"""Cognitive Layer — External Brain v2.

FastAPI service providing:
  - Knowledge Graph CRUD (kg_nodes + kg_edges in PostgreSQL)
  - Memory Ingestion Pipeline (git, calendar, Orbit, HA events, chat exports)
  - Thought Continuity Engine (open thread tracking)
  - Cognitive Load Monitor (mental-debt score)
  - Daily Briefing (LLM-generated morning narrative)
  - Reflection Mode (daily / weekly / monthly reports)

Port: 8230
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from . import db
from .config import settings
from .models import (
    CognitiveLoadStatus,
    DailyBriefing,
    Edge,
    EdgeCreate,
    GraphNeighbours,
    IngestResult,
    Node,
    NodeCreate,
    NodeUpdate,
    ReflectionReport,
    Thread,
    ThreadCreate,
    ThreadUpdate,
)
from . import knowledge_graph as kg
from . import continuity, cognitive_load, briefing, reflection
from .ingestion import git_activity, calendar as cal_ingest, orbit as orbit_ingest
from .ingestion.ha_events import HaEventsIngester
from .scheduler import CognitiveScheduler

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_ha_ingester: Optional[HaEventsIngester] = None
_nats = None
_scheduler = CognitiveScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ha_ingester, _nats

    await db.init_pool()

    # NATS connection for HA event ingestion and node-created events
    try:
        from shared.nats_client import NatsPublisher  # type: ignore[import]
        _nats = NatsPublisher(url=settings.nats_url)
        await _nats.connect()
        kg.set_nats(_nats)
        _ha_ingester = HaEventsIngester(_nats)
        await _ha_ingester.start()
    except Exception as exc:
        logger.warning("nats_unavailable error=%s — HA event ingestion disabled", exc)

    _scheduler.start()
    asyncio.create_task(_register_with_oracle())

    logger.info("cognitive_layer_started port=%d", settings.port)
    yield

    await _scheduler.stop()
    if _nats is not None:
        await _nats.close()
    await db.close_pool()
    logger.info("cognitive_layer_stopped")


app = FastAPI(
    title="Cognitive Layer — External Brain v2",
    version="1.0.0",
    lifespan=lifespan,
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
        "nats": "connected" if (_nats and _nats.connected) else "disconnected",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph — Nodes
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/nodes", response_model=Node, status_code=201)
async def create_node(data: NodeCreate):
    node = await kg.create_node(data)
    if not node:
        raise HTTPException(503, "Database unavailable")
    return node


@app.get("/api/v1/nodes", response_model=list[Node])
async def list_nodes(
    node_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await kg.list_nodes(node_type=node_type, source=source, limit=limit, offset=offset)


@app.get("/api/v1/nodes/search", response_model=list[Node])
async def search_nodes(q: str = Query(..., min_length=2), limit: int = Query(20, le=100)):
    return await kg.search_nodes(q, limit=limit)


@app.get("/api/v1/nodes/{node_id}", response_model=Node)
async def get_node(node_id: uuid.UUID):
    node = await kg.get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@app.patch("/api/v1/nodes/{node_id}", response_model=Node)
async def update_node(node_id: uuid.UUID, data: NodeUpdate):
    node = await kg.update_node(node_id, data)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@app.delete("/api/v1/nodes/{node_id}", status_code=204)
async def delete_node(node_id: uuid.UUID):
    deleted = await kg.delete_node(node_id)
    if not deleted:
        raise HTTPException(404, "Node not found")


@app.get("/api/v1/nodes/{node_id}/neighbours", response_model=GraphNeighbours)
async def get_neighbours(node_id: uuid.UUID):
    result = await kg.get_neighbours(node_id)
    if result.node is None:
        raise HTTPException(404, "Node not found")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph — Edges
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/edges", response_model=Edge, status_code=201)
async def create_edge(data: EdgeCreate):
    edge = await kg.create_edge(data)
    if not edge:
        raise HTTPException(503, "Database unavailable")
    return edge


@app.get("/api/v1/edges/{edge_id}", response_model=Edge)
async def get_edge(edge_id: uuid.UUID):
    edge = await kg.get_edge(edge_id)
    if not edge:
        raise HTTPException(404, "Edge not found")
    return edge


@app.delete("/api/v1/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: uuid.UUID):
    deleted = await kg.delete_edge(edge_id)
    if not deleted:
        raise HTTPException(404, "Edge not found")


# ─────────────────────────────────────────────────────────────────────────────
# Thought Continuity Engine
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/threads", response_model=Thread, status_code=201)
async def create_thread(data: ThreadCreate):
    thread = await continuity.create_thread(data)
    if not thread:
        raise HTTPException(503, "Database unavailable")
    return thread


@app.get("/api/v1/threads", response_model=list[Thread])
async def list_threads(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    return await continuity.list_threads(status=status, limit=limit, offset=offset)


@app.get("/api/v1/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: uuid.UUID):
    thread = await continuity.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return thread


@app.patch("/api/v1/threads/{thread_id}", response_model=Thread)
async def update_thread(thread_id: uuid.UUID, data: ThreadUpdate):
    thread = await continuity.update_thread(thread_id, data)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return thread


@app.post("/api/v1/threads/{thread_id}/close", response_model=Thread)
async def close_thread(thread_id: uuid.UUID):
    thread = await continuity.close_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return thread


@app.post("/api/v1/threads/{thread_id}/touch", response_model=Thread)
async def touch_thread(thread_id: uuid.UUID):
    thread = await continuity.touch_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return thread


@app.post("/api/v1/threads/maintenance")
async def run_maintenance():
    result = await continuity.run_maintenance()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Load
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/cognitive-load", response_model=CognitiveLoadStatus)
async def get_cognitive_load():
    return await cognitive_load.compute()


@app.get("/api/v1/cognitive-load/history")
async def get_cognitive_load_history(limit: int = Query(30, le=100)):
    samples = await cognitive_load.history(limit=limit)
    return samples


# ─────────────────────────────────────────────────────────────────────────────
# Daily Briefing
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/briefing", response_model=DailyBriefing)
async def get_briefing(target_date: Optional[date] = Query(None)):
    return await briefing.get_or_generate_briefing(target_date)


@app.post("/api/v1/briefing/regenerate", response_model=DailyBriefing)
async def regenerate_briefing(target_date: Optional[date] = Query(None)):
    return await briefing.generate_briefing(target_date)


# ─────────────────────────────────────────────────────────────────────────────
# Reflection Reports
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/reflection/daily", response_model=ReflectionReport)
async def daily_reflection(target_date: Optional[date] = Query(None)):
    return await reflection.get_or_generate_daily(target_date)


@app.get("/api/v1/reflection/weekly", response_model=ReflectionReport)
async def weekly_reflection(week_start: Optional[date] = Query(None)):
    return await reflection.get_or_generate_weekly(week_start)


@app.get("/api/v1/reflection/monthly", response_model=ReflectionReport)
async def monthly_reflection(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
):
    return await reflection.get_or_generate_monthly(year, month)


@app.get("/api/v1/reflection", response_model=list[ReflectionReport])
async def list_reflections(
    period_type: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
):
    return await reflection.list_reports(period_type=period_type, limit=limit)


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion Pipeline
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/ingest/git", response_model=IngestResult)
async def ingest_git(days: int = Query(7, ge=1, le=90)):
    return await git_activity.ingest_git_activity(since_days=days)


@app.post("/api/v1/ingest/calendar", response_model=IngestResult)
async def ingest_calendar(
    days_ahead: int = Query(7, ge=0, le=30),
    days_behind: int = Query(7, ge=0, le=90),
):
    return await cal_ingest.ingest_calendar(days_ahead=days_ahead, days_behind=days_behind)


@app.post("/api/v1/ingest/orbit", response_model=IngestResult)
async def ingest_orbit(days: int = Query(7, ge=1, le=90)):
    return await orbit_ingest.ingest_orbit(days=days)


@app.post("/api/v1/ingest/chat-export", response_model=IngestResult)
async def ingest_chat_export(export_path: str = Query(...), source_tag: str = Query("chat_export")):
    from .ingestion.chat_export import ingest_chat_export as _ingest
    return await _ingest(export_path, source_tag)


@app.post("/api/v1/ingest/all", response_model=list[IngestResult])
async def ingest_all(days: int = Query(7, ge=1, le=90)):
    """Run all ingesters (except chat export) in sequence."""
    results = []
    for coro in [
        git_activity.ingest_git_activity(since_days=days),
        cal_ingest.ingest_calendar(days_ahead=days, days_behind=days),
        orbit_ingest.ingest_orbit(days=days),
    ]:
        try:
            results.append(await coro)
        except Exception as exc:
            results.append(IngestResult(source="unknown", nodes_created=0, edges_created=0, errors=[str(exc)]))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Oracle registration
# ─────────────────────────────────────────────────────────────────────────────

async def _register_with_oracle() -> None:
    manifest = {
        "service_name": "cognitive-layer",
        "port": settings.port,
        "description": "External Brain v2 — KG, ingestion, thought continuity, cognitive load, briefing, reflection",
        "endpoints": [
            {"method": "GET",    "path": "/health",                         "purpose": "Health check"},
            {"method": "POST",   "path": "/api/v1/nodes",                   "purpose": "Create KG node"},
            {"method": "GET",    "path": "/api/v1/nodes",                   "purpose": "List KG nodes"},
            {"method": "GET",    "path": "/api/v1/nodes/search",            "purpose": "Search KG nodes"},
            {"method": "GET",    "path": "/api/v1/nodes/{id}",              "purpose": "Get KG node"},
            {"method": "PATCH",  "path": "/api/v1/nodes/{id}",              "purpose": "Update KG node"},
            {"method": "DELETE", "path": "/api/v1/nodes/{id}",              "purpose": "Delete KG node"},
            {"method": "GET",    "path": "/api/v1/nodes/{id}/neighbours",   "purpose": "Get node neighbours"},
            {"method": "POST",   "path": "/api/v1/edges",                   "purpose": "Create KG edge"},
            {"method": "GET",    "path": "/api/v1/threads",                 "purpose": "List thought threads"},
            {"method": "POST",   "path": "/api/v1/threads",                 "purpose": "Create thought thread"},
            {"method": "GET",    "path": "/api/v1/cognitive-load",          "purpose": "Current mental-debt score"},
            {"method": "GET",    "path": "/api/v1/briefing",                "purpose": "Daily briefing (LLM)"},
            {"method": "POST",   "path": "/api/v1/briefing/regenerate",     "purpose": "Regenerate briefing"},
            {"method": "GET",    "path": "/api/v1/reflection/daily",        "purpose": "Daily reflection report"},
            {"method": "GET",    "path": "/api/v1/reflection/weekly",       "purpose": "Weekly drift detector"},
            {"method": "GET",    "path": "/api/v1/reflection/monthly",      "purpose": "Monthly momentum report"},
            {"method": "POST",   "path": "/api/v1/ingest/git",              "purpose": "Ingest GitHub commits"},
            {"method": "POST",   "path": "/api/v1/ingest/calendar",         "purpose": "Ingest calendar events"},
            {"method": "POST",   "path": "/api/v1/ingest/orbit",            "purpose": "Ingest Orbit tasks/goals"},
            {"method": "POST",   "path": "/api/v1/ingest/chat-export",      "purpose": "Ingest chat export JSON"},
            {"method": "POST",   "path": "/api/v1/ingest/all",              "purpose": "Run all ingesters"},
        ],
        "nats_subjects": [
            {"subject": "ha.state.>",            "direction": "subscribe", "purpose": "HA state-change ingestion"},
            {"subject": "cognitive.node.created", "direction": "publish",  "purpose": "KG node created event"},
        ],
        "source_paths": [{"repo": "claude", "paths": ["services/cognitive-layer/"]}],
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{settings.oracle_url}/oracle/register", json=manifest)
        logger.info("cognitive_layer oracle_registered")
    except Exception as exc:
        logger.warning("cognitive_layer oracle_registration_failed error=%s", exc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
