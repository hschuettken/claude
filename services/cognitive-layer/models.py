"""Pydantic models for the Cognitive Layer API."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph
# ─────────────────────────────────────────────────────────────────────────────

class NodeCreate(BaseModel):
    node_type: str  # page|meeting|chat|git_commit|ha_event|calendar_event|orbit_task|orbit_goal|thought|concept
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    source_id: Optional[str] = None


class NodeUpdate(BaseModel):
    label: Optional[str] = None
    properties: Optional[dict[str, Any]] = None


class Node(BaseModel):
    id: uuid.UUID
    node_type: str
    label: str
    properties: dict[str, Any]
    source: Optional[str]
    source_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class EdgeCreate(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation_type: str  # RELATES_TO|BLOCKS|DEPENDS_ON|PART_OF|CREATED_BY|DISCUSSED_IN|LEADS_TO
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation_type: str
    weight: float
    properties: dict[str, Any]
    created_at: datetime


class GraphNeighbours(BaseModel):
    node: Node
    edges: list[Edge]
    neighbours: list[Node]


# ─────────────────────────────────────────────────────────────────────────────
# Thought Continuity Engine
# ─────────────────────────────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: str
    summary: Optional[str] = None
    node_ids: list[uuid.UUID] = Field(default_factory=list)


class ThreadUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None  # open|dormant|closed
    node_ids: Optional[list[uuid.UUID]] = None


class Thread(BaseModel):
    id: uuid.UUID
    title: str
    summary: Optional[str]
    status: str
    recurrence: int
    last_seen_at: datetime
    created_at: datetime
    node_ids: list[uuid.UUID]


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Load
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveLoadSample(BaseModel):
    id: uuid.UUID
    sampled_at: datetime
    open_threads: int
    overdue_tasks: int
    unprocessed_events: int
    debt_score: float
    breakdown: dict[str, Any]


class CognitiveLoadStatus(BaseModel):
    debt_score: float
    open_threads: int
    overdue_tasks: int
    unprocessed_events: int
    breakdown: dict[str, float]
    label: str  # low|moderate|high|critical


# ─────────────────────────────────────────────────────────────────────────────
# Briefing & Reflection
# ─────────────────────────────────────────────────────────────────────────────

class DailyBriefing(BaseModel):
    id: uuid.UUID
    date: date
    narrative: str
    context: dict[str, Any]
    generated_at: datetime


class ReflectionReport(BaseModel):
    id: uuid.UUID
    period_type: str
    period_start: date
    period_end: date
    content: str
    metrics: dict[str, Any]
    generated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────────

class IngestResult(BaseModel):
    source: str
    nodes_created: int
    edges_created: int
    errors: list[str] = Field(default_factory=list)
