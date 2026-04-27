"""Pydantic models for the Agent Economy API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Agent Registry
# ─────────────────────────────────────────────────────────────────────────────

AGENT_TYPES = {
    "main", "architect", "dev", "qa", "devops",
    "team-lead", "backlog-agent", "spec-retro", "custom",
}

AGENT_STATUSES = {"active", "inactive", "busy"}


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    agent_type: str
    capabilities: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    budget_tokens_total: int = Field(default=0, ge=0)


class AgentUpdate(BaseModel):
    description: Optional[str] = None
    capabilities: Optional[list[str]] = None
    status: Optional[str] = None
    budget_tokens_total: Optional[int] = Field(default=None, ge=0)


class Agent(BaseModel):
    id: uuid.UUID
    name: str
    agent_type: str
    capabilities: list[str]
    description: Optional[str]
    status: str
    spawned_by: Optional[uuid.UUID]
    ttl_seconds: Optional[int]
    expires_at: Optional[datetime]
    budget_tokens_total: int
    budget_tokens_used: int
    reputation_score: float
    tasks_completed: int
    tasks_failed: int
    created_at: datetime
    updated_at: datetime


class AgentStats(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    tasks_completed: int
    tasks_failed: int
    success_rate: float
    reputation_score: float
    budget_tokens_total: int
    budget_tokens_used: int
    budget_remaining: int  # -1 = unlimited
    tokens_this_week: int


# ─────────────────────────────────────────────────────────────────────────────
# Task Broker
# ─────────────────────────────────────────────────────────────────────────────

TASK_STATUSES = {"created", "claimed", "completed", "failed"}


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_type: str
    priority: int = Field(default=3, ge=1, le=5)
    created_by: Optional[uuid.UUID] = None
    nats_subject: Optional[str] = None
    nats_payload: dict[str, Any] = Field(default_factory=dict)
    budget_tokens_max: int = Field(default=10000, ge=0)


class TaskClaimRequest(BaseModel):
    agent_id: uuid.UUID


class TaskCompleteRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = Field(default=0, ge=0)
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)


class TaskFailRequest(BaseModel):
    error: str
    tokens_used: int = Field(default=0, ge=0)


class Task(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str]
    task_type: str
    status: str
    priority: int
    assigned_to: Optional[uuid.UUID]
    created_by: Optional[uuid.UUID]
    nats_subject: Optional[str]
    nats_payload: dict[str, Any]
    budget_tokens_max: int
    tokens_used: int
    quality_score: Optional[float]
    result: Optional[dict[str, Any]]
    error: Optional[str]
    claimed_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────────────────────

class BudgetLogCreate(BaseModel):
    agent_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None
    tokens_used: int = Field(..., ge=1)
    model_name: Optional[str] = None
    operation: Optional[str] = None


class BudgetLogEntry(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    task_id: Optional[uuid.UUID]
    tokens_used: int
    model_name: Optional[str]
    operation: Optional[str]
    created_at: datetime


class BudgetSummary(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    total_tokens: int
    budget_limit: int  # 0 = unlimited
    entries: int
    top_operations: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# Spawn Requests — self-spawning workflow
# ─────────────────────────────────────────────────────────────────────────────

SPAWN_STATUSES = {"pending", "approved", "rejected", "cancelled"}


class SpawnRequestCreate(BaseModel):
    requested_by: uuid.UUID
    template_name: str = Field(..., min_length=1, max_length=128)
    purpose: str
    capabilities: list[str] = Field(default_factory=list)
    ttl_seconds: Optional[int] = Field(default=None, gt=0)


class SpawnApproveRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)


class SpawnRejectRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)
    reason: str


class SpawnRequest(BaseModel):
    id: uuid.UUID
    requested_by: uuid.UUID
    template_name: str
    purpose: str
    capabilities: list[str]
    ttl_seconds: Optional[int]
    status: str
    approved_by: Optional[str]
    spawned_agent_id: Optional[uuid.UUID]
    rejection_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Auth — Bifrost-style JWT tokens
# ─────────────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    agent_name: str
    secret: str  # shared secret for the agent (stored in .env)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_agents: int
    active_agents: int
    busy_agents: int
    total_tasks: int
    tasks_created: int
    tasks_claimed: int
    tasks_completed: int
    tasks_failed: int
    avg_reputation_score: float
    total_tokens_used: int
    pending_spawn_requests: int
    top_agents: list[AgentStats]
