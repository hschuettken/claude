"""Tests for the Self-Optimizing Infrastructure service.

All tests run without a real database, NATS, or external APIs.
db.py returns None/[] when pool is absent; all modules handle that gracefully.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts():
    return datetime.now(timezone.utc)


def _make_rule_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "name": "test_rule",
        "description": "A test rule",
        "condition_type": "heartbeat_missing",
        "condition_params": {},
        "action_type": "restart_service",
        "action_params": {},
        "risk_level": "low",
        "auto_approve": True,
        "enabled": True,
        "cooldown_minutes": 10,
        "last_fired_at": None,
        "created_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_decision_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "rule_id": uuid.uuid4(),
        "rule_name": "test_rule",
        "trigger_data": {},
        "action_type": "restart_service",
        "action_params": {"service_name": "pv-forecast"},
        "risk_level": "low",
        "status": "pending",
        "auto_approved": False,
        "approved_by": None,
        "result": None,
        "created_at": _ts(),
        "approved_at": None,
        "executed_at": None,
    }
    defaults.update(kwargs)
    return defaults


def _make_proposal_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "title": "Scale CPU on node-1",
        "description": "Node-1 is at 85% CPU",
        "proposal_type": "scale_cpu",
        "resource_target": "node-1",
        "estimated_impact": {"headroom_gain_pct": 15.0},
        "data_summary": {"current_cpu_pct": 85.0},
        "status": "pending",
        "created_at": _ts(),
        "resolved_at": None,
        "resolved_by": None,
    }
    defaults.update(kwargs)
    return defaults


def _make_chaos_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "experiment_type": "service_kill",
        "target": "pv-forecast",
        "status": "passed",
        "started_at": _ts(),
        "completed_at": _ts(),
        "recovery_time_seconds": 12,
        "result": {"service": "pv-forecast", "recovery_seconds": 12},
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Config tests
# ─────────────────────────────────────────────────────────────────────────────

def test_config_defaults():
    from self_optimizing_infra.config import Settings
    s = Settings()
    assert s.port == 8242
    assert s.decision_loop_interval_seconds == 60
    assert s.l1_poll_interval_seconds == 120
    assert s.chaos_enabled is False
    assert s.chaos_max_kill_fraction == 0.3


# ─────────────────────────────────────────────────────────────────────────────
# Models tests
# ─────────────────────────────────────────────────────────────────────────────

def test_service_health_model():
    from self_optimizing_infra.models import ServiceHealth
    svc = ServiceHealth(
        service_name="pv-forecast",
        monitor_level="L0",
        status="online",
    )
    assert svc.service_name == "pv-forecast"
    assert svc.monitor_level == "L0"
    assert svc.metadata == {}


def test_node_health_model():
    from self_optimizing_infra.models import NodeHealth
    node = NodeHealth(
        node_id="node-1",
        node_name="homelab-node-1",
        status="online",
        cpu_percent=45.0,
        source="proxmox",
    )
    assert node.cpu_percent == 45.0
    assert node.source == "proxmox"


def test_decision_rule_create_model():
    from self_optimizing_infra.models import DecisionRuleCreate
    rule = DecisionRuleCreate(
        name="my_rule",
        condition_type="heartbeat_missing",
        action_type="restart_service",
        risk_level="low",
        auto_approve=True,
    )
    assert rule.risk_level == "low"
    assert rule.auto_approve is True


def test_evolution_proposal_create_model():
    from self_optimizing_infra.models import EvolutionProposalCreate
    p = EvolutionProposalCreate(
        title="Add RAM to node-2",
        proposal_type="scale_memory",
        resource_target="node-2",
        estimated_impact={"headroom_gain_pct": 20},
    )
    assert p.proposal_type == "scale_memory"


def test_chaos_run_create_model():
    from self_optimizing_infra.models import ChaosRunCreate
    cr = ChaosRunCreate(experiment_type="service_kill", target="dashboard")
    assert cr.experiment_type == "service_kill"
    assert cr.target == "dashboard"


# ─────────────────────────────────────────────────────────────────────────────
# L0 Monitor tests
# ─────────────────────────────────────────────────────────────────────────────

def test_l0_on_heartbeat_updates_health():
    from self_optimizing_infra import monitors
    monitors._service_health.clear()
    monitors._heartbeat_ts.clear()

    monitors.on_heartbeat("pv-forecast", {"status": "online", "uptime_seconds": 3600})
    svcs = monitors.get_l0_services()
    assert len(svcs) == 1
    assert svcs[0].service_name == "pv-forecast"
    assert svcs[0].status == "online"
    assert svcs[0].monitor_level == "L0"


def test_l0_check_stale_services():
    from self_optimizing_infra import monitors
    from self_optimizing_infra.models import ServiceHealth

    monitors._heartbeat_ts.clear()
    monitors._service_health.clear()

    # Inject a stale heartbeat (600s ago)
    monitors._heartbeat_ts["stale-svc"] = time.monotonic() - 600
    monitors._service_health["stale-svc"] = ServiceHealth(
        service_name="stale-svc",
        monitor_level="L0",
        status="online",
    )

    stale = monitors.check_stale_services()
    assert "stale-svc" in stale
    # Status should be updated to offline
    assert monitors._service_health["stale-svc"].status == "offline"


def test_l0_fresh_heartbeat_not_stale():
    from self_optimizing_infra import monitors
    monitors._heartbeat_ts["fresh-svc"] = time.monotonic()
    monitors._service_health["fresh-svc"] = MagicMock(status="online")

    stale = monitors.check_stale_services()
    assert "fresh-svc" not in stale


def test_get_infra_snapshot_returns_dict():
    from self_optimizing_infra import monitors
    monitors._service_health.clear()
    monitors._heartbeat_ts.clear()
    monitors._node_health.clear()

    snapshot = monitors.get_infra_snapshot()
    assert "total_services" in snapshot
    assert "total_nodes" in snapshot
    assert "offline_services" in snapshot
    assert "snapshot_at" in snapshot


# ─────────────────────────────────────────────────────────────────────────────
# Decision engine — condition evaluation tests
# ─────────────────────────────────────────────────────────────────────────────

def test_evaluate_condition_heartbeat_missing():
    from self_optimizing_infra.decision_engine import _evaluate_condition
    from self_optimizing_infra.models import DecisionRule

    rule = DecisionRule(
        id=uuid.uuid4(),
        name="r",
        condition_type="heartbeat_missing",
        condition_params={},
        action_type="restart_service",
        action_params={},
        risk_level="low",
        auto_approve=True,
        enabled=True,
        cooldown_minutes=10,
        created_at=_ts(),
    )
    snapshot = {
        "offline_services": ["pv-forecast"],
        "stale_services": [],
        "offline_nodes": [],
        "high_cpu_nodes": [],
        "high_mem_nodes": [],
    }
    triggers = _evaluate_condition(rule, snapshot)
    assert len(triggers) == 1
    assert triggers[0]["service"] == "pv-forecast"


def test_evaluate_condition_cpu_high():
    from self_optimizing_infra.decision_engine import _evaluate_condition
    from self_optimizing_infra.models import DecisionRule

    rule = DecisionRule(
        id=uuid.uuid4(),
        name="r",
        condition_type="cpu_high",
        condition_params={"threshold_pct": 85},
        action_type="alert_telegram",
        action_params={},
        risk_level="low",
        auto_approve=True,
        enabled=True,
        cooldown_minutes=30,
        created_at=_ts(),
    )
    snapshot = {
        "offline_services": [],
        "stale_services": [],
        "offline_nodes": [],
        "high_cpu_nodes": [{"name": "node-1", "cpu_percent": 90.0}],
        "high_mem_nodes": [],
    }
    triggers = _evaluate_condition(rule, snapshot)
    assert len(triggers) == 1
    assert triggers[0]["node"] == "node-1"


def test_evaluate_condition_no_match():
    from self_optimizing_infra.decision_engine import _evaluate_condition
    from self_optimizing_infra.models import DecisionRule

    rule = DecisionRule(
        id=uuid.uuid4(),
        name="r",
        condition_type="heartbeat_missing",
        condition_params={},
        action_type="restart_service",
        action_params={},
        risk_level="low",
        auto_approve=True,
        enabled=True,
        cooldown_minutes=10,
        created_at=_ts(),
    )
    snapshot = {
        "offline_services": [],
        "stale_services": [],
        "offline_nodes": [],
        "high_cpu_nodes": [],
        "high_mem_nodes": [],
    }
    triggers = _evaluate_condition(rule, snapshot)
    assert triggers == []


def test_evaluate_condition_mem_high():
    from self_optimizing_infra.decision_engine import _evaluate_condition
    from self_optimizing_infra.models import DecisionRule

    rule = DecisionRule(
        id=uuid.uuid4(),
        name="r",
        condition_type="mem_high",
        condition_params={"threshold_pct": 90},
        action_type="alert_telegram",
        action_params={},
        risk_level="low",
        auto_approve=True,
        enabled=True,
        cooldown_minutes=30,
        created_at=_ts(),
    )
    snapshot = {
        "offline_services": [],
        "stale_services": [],
        "offline_nodes": [],
        "high_cpu_nodes": [],
        "high_mem_nodes": [{"name": "node-2", "mem_percent": 95.0}],
    }
    triggers = _evaluate_condition(rule, snapshot)
    assert len(triggers) == 1
    assert triggers[0]["node"] == "node-2"


def test_evaluate_condition_node_down():
    from self_optimizing_infra.decision_engine import _evaluate_condition
    from self_optimizing_infra.models import DecisionRule

    rule = DecisionRule(
        id=uuid.uuid4(),
        name="r",
        condition_type="node_down",
        condition_params={},
        action_type="create_task",
        action_params={},
        risk_level="medium",
        auto_approve=True,
        enabled=True,
        cooldown_minutes=20,
        created_at=_ts(),
    )
    snapshot = {
        "offline_services": [],
        "stale_services": [],
        "offline_nodes": ["proxmox:node-3"],
        "high_cpu_nodes": [],
        "high_mem_nodes": [],
    }
    triggers = _evaluate_condition(rule, snapshot)
    assert len(triggers) == 1
    assert "proxmox:node-3" in triggers[0]["node"]


# ─────────────────────────────────────────────────────────────────────────────
# Decision engine — DB-backed functions (no-pool graceful fallback)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_rules_no_db():
    from self_optimizing_infra import decision_engine as de
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetch = AsyncMock(return_value=[])
        rules = await de.list_rules()
        assert rules == []


@pytest.mark.asyncio
async def test_create_decision_no_db():
    from self_optimizing_infra import decision_engine as de
    from self_optimizing_infra.models import DecisionCreate
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetchrow = AsyncMock(return_value=None)
        dc = DecisionCreate(
            rule_name="test",
            trigger_data={"service": "pv-forecast"},
            action_type="restart_service",
            action_params={"service_name": "pv-forecast"},
        )
        result = await de.create_decision(dc)
        assert result is None


@pytest.mark.asyncio
async def test_approve_decision_updates_row():
    from self_optimizing_infra import decision_engine as de
    row = _make_decision_row(status="approved", approved_by="human", approved_at=_ts())
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetchrow = AsyncMock(return_value=row)
        d = await de.approve_decision(uuid.uuid4(), "human")
        assert d is not None
        assert d.approved_by == "human"


@pytest.mark.asyncio
async def test_seed_default_rules_skips_when_populated():
    from self_optimizing_infra import decision_engine as de
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetchval = AsyncMock(return_value=5)  # Already has rules
        mock_db.execute = AsyncMock()
        await de.seed_default_rules()
        mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_reject_decision_uses_correct_param_index():
    """Regression: reject_decision must use $3 for id (not $2 which is the reason string)."""
    from self_optimizing_infra import decision_engine as de
    row = _make_decision_row(
        status="rejected",
        approved_by="human",
        result="rejected: testing",
        approved_at=_ts(),
    )
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetchrow = AsyncMock(return_value=row)
        d = await de.reject_decision(uuid.uuid4(), "human", "testing")
        assert d is not None
        assert d.status == "rejected"
        assert d.approved_by == "human"
        # Verify the SQL sends 3 positional params and references $3 for the id
        call_args = mock_db.fetchrow.call_args
        query: str = call_args[0][0]
        params = call_args[0][1:]
        assert "$3" in query, "WHERE id must use $3 (decision_id), not $2 (reason string)"
        assert len(params) == 3, "Expected (rejected_by, reason, decision_id)"


@pytest.mark.asyncio
async def test_evaluate_rules_no_db():
    """evaluate_rules returns empty list when DB is unavailable."""
    from self_optimizing_infra import decision_engine as de
    snapshot = {
        "offline_services": ["pv-forecast"],
        "stale_services": [],
        "offline_nodes": [],
        "high_cpu_nodes": [],
        "high_mem_nodes": [],
    }
    with patch("self_optimizing_infra.decision_engine.db") as mock_db:
        mock_db.fetch = AsyncMock(return_value=[])
        decisions = await de.evaluate_rules(snapshot)
        assert decisions == []


# ─────────────────────────────────────────────────────────────────────────────
# Evolution tests
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_proposals_high_cpu():
    from self_optimizing_infra.evolution import _generate_proposals

    uptime = {"pv-forecast": 99.5}
    node_util = {"node-1": {"cpu_pct": 90.0, "mem_pct": 50.0, "disk_pct": 40.0, "status": "online", "source": "proxmox"}}

    proposals = _generate_proposals(uptime, node_util)
    types = {p.proposal_type for p in proposals}
    assert "scale_cpu" in types


def test_generate_proposals_high_mem():
    from self_optimizing_infra.evolution import _generate_proposals

    uptime = {}
    node_util = {"node-2": {"cpu_pct": 30.0, "mem_pct": 92.0, "disk_pct": 50.0, "status": "online", "source": "proxmox"}}

    proposals = _generate_proposals(uptime, node_util)
    types = {p.proposal_type for p in proposals}
    assert "scale_memory" in types


def test_generate_proposals_low_uptime():
    from self_optimizing_infra.evolution import _generate_proposals

    uptime = {"flaky-svc": 80.0}
    node_util = {}

    proposals = _generate_proposals(uptime, node_util)
    types = {p.proposal_type for p in proposals}
    assert "improve_reliability" in types


def test_generate_proposals_offline_node():
    from self_optimizing_infra.evolution import _generate_proposals

    uptime = {}
    node_util = {"dead-node": {"cpu_pct": 0, "mem_pct": 0, "disk_pct": 0, "status": "offline", "source": "k3s"}}

    proposals = _generate_proposals(uptime, node_util)
    types = {p.proposal_type for p in proposals}
    assert "decommission_node" in types


def test_generate_proposals_healthy_infra():
    from self_optimizing_infra.evolution import _generate_proposals

    uptime = {"svc-a": 99.9, "svc-b": 100.0}
    node_util = {
        "node-1": {"cpu_pct": 30.0, "mem_pct": 40.0, "disk_pct": 20.0, "status": "online", "source": "proxmox"},
    }

    proposals = _generate_proposals(uptime, node_util)
    assert proposals == []


@pytest.mark.asyncio
async def test_list_proposals_no_db():
    from self_optimizing_infra import evolution as evo
    with patch("self_optimizing_infra.evolution.db") as mock_db:
        mock_db.fetch = AsyncMock(return_value=[])
        proposals = await evo.list_proposals()
        assert proposals == []


@pytest.mark.asyncio
async def test_approve_proposal():
    from self_optimizing_infra import evolution as evo
    row = _make_proposal_row(status="approved", resolved_by="Henning", resolved_at=_ts())
    with patch("self_optimizing_infra.evolution.db") as mock_db:
        mock_db.fetchrow = AsyncMock(return_value=row)
        p = await evo.approve_proposal(uuid.uuid4(), "Henning", "looks good")
        assert p is not None
        assert p.status == "approved"


# ─────────────────────────────────────────────────────────────────────────────
# Chaos tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_chaos_run_no_db():
    from self_optimizing_infra import chaos
    from self_optimizing_infra.models import ChaosRunCreate
    with patch("self_optimizing_infra.chaos.db") as mock_db:
        mock_db.fetchrow = AsyncMock(return_value=None)
        run = await chaos.create_run(ChaosRunCreate(experiment_type="service_kill", target="x"))
        assert run is None


@pytest.mark.asyncio
async def test_generate_resilience_report_empty():
    from self_optimizing_infra import chaos
    with patch("self_optimizing_infra.chaos.db") as mock_db:
        mock_db.fetch = AsyncMock(return_value=[])
        report = await chaos.generate_resilience_report()
        assert report.total_experiments == 0
        assert report.resilience_score == 1.0
        assert report.avg_recovery_time_seconds is None


@pytest.mark.asyncio
async def test_generate_resilience_report_with_runs():
    from self_optimizing_infra import chaos
    rows = [
        _make_chaos_row(status="passed", recovery_time_seconds=10),
        _make_chaos_row(status="passed", recovery_time_seconds=20),
        _make_chaos_row(status="failed", recovery_time_seconds=None),
    ]
    with patch("self_optimizing_infra.chaos.db") as mock_db:
        mock_db.fetch = AsyncMock(return_value=rows)
        report = await chaos.generate_resilience_report()
        assert report.total_experiments == 3
        assert report.passed == 2
        assert report.failed == 1
        assert abs(report.resilience_score - 2 / 3) < 0.01
        assert report.avg_recovery_time_seconds == 15.0


@pytest.mark.asyncio
async def test_run_latency_injection_simulation():
    from self_optimizing_infra import chaos
    from self_optimizing_infra.models import ChaosRun

    run = ChaosRun(
        id=uuid.uuid4(),
        experiment_type="latency_injection",
        target="dashboard",
        status="running",
        started_at=_ts(),
    )
    status, recovery, result = await chaos._run_latency_injection(run)
    assert status == "passed"
    assert "simulated_latency_ms" in result


@pytest.mark.asyncio
async def test_run_node_failure_simulation():
    from self_optimizing_infra import chaos, monitors
    from self_optimizing_infra.models import ChaosRun, NodeHealth

    monitors._node_health["test-node"] = NodeHealth(
        node_id="test-node",
        node_name="test-node",
        status="online",
        source="proxmox",
    )

    run = ChaosRun(
        id=uuid.uuid4(),
        experiment_type="node_failure",
        target="test-node",
        status="running",
        started_at=_ts(),
    )
    status, recovery, result = await chaos._run_node_failure(run)
    assert status == "passed"
    assert result.get("simulation") is True
    # Node should be restored to online after the experiment
    assert monitors._node_health.get("test-node", MagicMock(status="online")).status == "online"


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app integration tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def test_client():
    from httpx import AsyncClient, ASGITransport
    from self_optimizing_infra.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_monitors_services_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/monitors/services")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_monitors_nodes_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/monitors/nodes")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_monitors_snapshot_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/monitors/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_services" in data


@pytest.mark.asyncio
async def test_decisions_rules_list_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/decisions/rules")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_decisions_list_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/decisions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_evolution_proposals_list_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/evolution/proposals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_chaos_runs_list_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/chaos/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_dashboard_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "services_online" in data
        assert "decision_engine_active" in data


@pytest.mark.asyncio
async def test_decisions_not_found(test_client):
    async with test_client as client:
        resp = await client.get(f"/api/v1/decisions/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_proposals_not_found(test_client):
    async with test_client as client:
        resp = await client.get(f"/api/v1/evolution/proposals/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chaos_run_not_found(test_client):
    async with test_client as client:
        resp = await client.get(f"/api/v1/chaos/runs/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_l1_poll_endpoint(test_client):
    async with test_client as client:
        resp = await client.post("/api/v1/monitors/poll")
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_trigger_evaluation_endpoint(test_client):
    async with test_client as client:
        resp = await client.post("/api/v1/decisions/evaluate")
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_trigger_analysis_endpoint(test_client):
    async with test_client as client:
        resp = await client.post("/api/v1/evolution/analyze")
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_trigger_chaos_sweep_endpoint(test_client):
    async with test_client as client:
        resp = await client.post("/api/v1/chaos/sweep")
        assert resp.status_code == 202
        data = resp.json()
        assert "chaos_enabled" in data


@pytest.mark.asyncio
async def test_resilience_report_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/chaos/resilience-report")
        assert resp.status_code == 200
        data = resp.json()
        assert "resilience_score" in data
        assert "total_experiments" in data


@pytest.mark.asyncio
async def test_evolution_report_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/api/v1/evolution/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "generated_at" in data
        assert "proposals" in data
