"""Pydantic models for Self-Optimizing Infrastructure service."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# L0 / L1 / L2 Service Health
# ─────────────────────────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    id: Optional[uuid.UUID] = None
    service_name: str
    monitor_level: str  # L0, L1, L2
    status: str  # online, offline, degraded, unknown
    last_seen: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class NodeHealth(BaseModel):
    node_id: str
    node_name: str
    status: str  # online, offline, degraded
    cpu_percent: Optional[float] = None
    mem_percent: Optional[float] = None
    disk_percent: Optional[float] = None
    uptime_seconds: Optional[int] = None
    source: str  # proxmox, bootstrap, k3s
    metadata: dict[str, Any] = Field(default_factory=dict)
    checked_at: Optional[datetime] = None


class InfraSnapshot(BaseModel):
    services: list[ServiceHealth]
    nodes: list[NodeHealth]
    snapshot_at: datetime
    l0_online: int = 0
    l0_offline: int = 0
    l1_online: int = 0
    l1_offline: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Decision Engine
# ─────────────────────────────────────────────────────────────────────────────

class DecisionRuleCreate(BaseModel):
    name: str
    description: str = ""
    condition_type: str  # heartbeat_missing, cpu_high, node_down, service_degraded
    condition_params: dict[str, Any] = Field(default_factory=dict)
    action_type: str   # restart_service, alert_telegram, create_task, reboot_node
    action_params: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"  # low, medium, high
    auto_approve: bool = False
    enabled: bool = True
    cooldown_minutes: int = 10


class DecisionRule(DecisionRuleCreate):
    id: uuid.UUID
    created_at: datetime


class DecisionCreate(BaseModel):
    rule_id: Optional[uuid.UUID] = None
    rule_name: str
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    action_type: str
    action_params: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"
    auto_approved: bool = False


class Decision(DecisionCreate):
    id: uuid.UUID
    status: str  # pending, approved, rejected, executing, done, failed
    approved_by: Optional[str] = None
    result: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None


class DecisionApproveRequest(BaseModel):
    approved_by: str = "human"


class DecisionRejectRequest(BaseModel):
    rejected_by: str = "human"
    reason: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Infra Evolution Proposals
# ─────────────────────────────────────────────────────────────────────────────

class EvolutionProposalCreate(BaseModel):
    title: str
    description: str = ""
    proposal_type: str  # add_node, remove_node, resize_service, upgrade_version, rebalance_workload
    resource_target: str = ""  # which node/service this affects
    estimated_impact: dict[str, Any] = Field(default_factory=dict)
    data_summary: dict[str, Any] = Field(default_factory=dict)


class EvolutionProposal(EvolutionProposalCreate):
    id: uuid.UUID
    status: str  # pending, approved, rejected, implemented
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class EvolutionProposalResolve(BaseModel):
    resolved_by: str
    reason: str = ""


class EvolutionReport(BaseModel):
    generated_at: datetime
    analysis_period_days: int
    service_uptime_summary: dict[str, float]  # service → uptime %
    node_utilization_summary: dict[str, dict[str, Any]]  # node → {cpu, mem, disk, status, source}
    proposals: list[EvolutionProposal]
    recommendations_count: int


# ─────────────────────────────────────────────────────────────────────────────
# Chaos Testing
# ─────────────────────────────────────────────────────────────────────────────

class ChaosRunCreate(BaseModel):
    experiment_type: str  # service_kill, node_failure, latency_injection
    target: str  # service name or node id


class ChaosRun(ChaosRunCreate):
    id: uuid.UUID
    status: str  # running, passed, failed, skipped
    started_at: datetime
    completed_at: Optional[datetime] = None
    recovery_time_seconds: Optional[int] = None
    result: dict[str, Any] = Field(default_factory=dict)


class ResilienceReport(BaseModel):
    generated_at: datetime
    total_experiments: int
    passed: int
    failed: int
    skipped: int
    avg_recovery_time_seconds: Optional[float]
    experiments: list[ChaosRun]
    resilience_score: float  # 0.0–1.0


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class SoiDashboard(BaseModel):
    services_online: int
    services_offline: int
    nodes_online: int
    nodes_offline: int
    open_decisions: int
    auto_approved_today: int
    open_proposals: int
    last_chaos_run: Optional[datetime]
    chaos_resilience_score: Optional[float]
    decision_engine_active: bool
