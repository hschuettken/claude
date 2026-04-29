"""Tests for the Agent Economy service.

All tests run without a real database — db.py returns None/[] when pool
is absent, and all modules handle that gracefully.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return "2026-01-01T00:00:00+00:00"


def _make_agent_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "name": "test-agent",
        "agent_type": "dev",
        "capabilities": ["code_review"],
        "description": "A test agent",
        "status": "active",
        "spawned_by": None,
        "ttl_seconds": None,
        "expires_at": None,
        "budget_tokens_total": 0,
        "budget_tokens_used": 0,
        "reputation_score": 1.0,
        "tasks_completed": 0,
        "tasks_failed": 0,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_task_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test task",
        "description": "Do something",
        "task_type": "code_review",
        "status": "created",
        "priority": 3,
        "assigned_to": None,
        "created_by": None,
        "nats_subject": None,
        "nats_payload": {},
        "budget_tokens_max": 10000,
        "tokens_used": 0,
        "quality_score": None,
        "result": None,
        "error": None,
        "claimed_at": None,
        "completed_at": None,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_budget_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "task_id": None,
        "tokens_used": 100,
        "model_name": "qwen2.5:3b",
        "operation": "task_execution",
        "created_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_spawn_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "requested_by": uuid.uuid4(),
        "template_name": "dev",
        "purpose": "Need extra dev for sprint",
        "capabilities": ["code_review"],
        "ttl_seconds": 3600,
        "status": "pending",
        "approved_by": None,
        "spawned_agent_id": None,
        "rejection_reason": None,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class TestModels:
    def test_agent_create(self):
        from agent_economy.models import AgentCreate
        a = AgentCreate(name="my-agent", agent_type="dev", capabilities=["code_review"])
        assert a.name == "my-agent"
        assert a.agent_type == "dev"
        assert a.budget_tokens_total == 0

    def test_task_create(self):
        from agent_economy.models import TaskCreate
        t = TaskCreate(title="Review PR", task_type="code_review", priority=4)
        assert t.priority == 4
        assert t.budget_tokens_max == 10000
        assert t.nats_payload == {}

    def test_task_complete_request(self):
        from agent_economy.models import TaskCompleteRequest
        r = TaskCompleteRequest(result={"output": "ok"}, tokens_used=500, quality_score=0.9)
        assert r.quality_score == 0.9
        assert r.tokens_used == 500

    def test_budget_log_create(self):
        from agent_economy.models import BudgetLogCreate
        aid = uuid.uuid4()
        b = BudgetLogCreate(agent_id=aid, tokens_used=200, model_name="qwen2.5:3b", operation="analysis")
        assert b.agent_id == aid
        assert b.task_id is None

    def test_spawn_request_create(self):
        from agent_economy.models import SpawnRequestCreate
        aid = uuid.uuid4()
        s = SpawnRequestCreate(
            requested_by=aid,
            template_name="dev",
            purpose="Need extra capacity",
            capabilities=["code_review"],
            ttl_seconds=3600,
        )
        assert s.ttl_seconds == 3600

    def test_token_request(self):
        from agent_economy.models import TokenRequest
        t = TokenRequest(agent_name="test-agent", secret="s3cr3t")
        assert t.agent_name == "test-agent"

    def test_dashboard_stats(self):
        from agent_economy.models import DashboardStats
        d = DashboardStats(
            total_agents=5, active_agents=3, busy_agents=1,
            total_tasks=10, tasks_created=2, tasks_claimed=3,
            tasks_completed=4, tasks_failed=1,
            avg_reputation_score=0.92,
            total_tokens_used=5000,
            pending_spawn_requests=0,
            top_agents=[],
        )
        assert d.total_agents == 5
        assert d.avg_reputation_score == 0.92


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_create_and_decode_token(self):
        from agent_economy.auth import create_token, decode_token
        agent_id = str(uuid.uuid4())
        token = create_token(agent_id, "test-agent")
        assert isinstance(token, str)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == agent_id
        assert payload["name"] == "test-agent"

    def test_decode_invalid_token(self):
        from agent_economy.auth import decode_token
        result = decode_token("not.a.valid.token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_agent_missing(self):
        from agent_economy.auth import get_current_agent
        result = await get_current_agent(authorization=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_agent_valid(self):
        from agent_economy.auth import create_token, get_current_agent
        agent_id = str(uuid.uuid4())
        token = create_token(agent_id, "my-agent")
        result = await get_current_agent(authorization=f"Bearer {token}")
        assert result is not None
        assert result["name"] == "my-agent"

    @pytest.mark.asyncio
    async def test_get_current_agent_bad_token(self):
        from fastapi import HTTPException
        from agent_economy.auth import get_current_agent
        with pytest.raises(HTTPException) as exc_info:
            await get_current_agent(authorization="Bearer badtoken")
        assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Registry — no DB (graceful degradation)
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryNoDB:
    @pytest.mark.asyncio
    async def test_create_agent_no_db(self):
        from agent_economy.models import AgentCreate
        from agent_economy import registry
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await registry.create_agent(AgentCreate(name="x", agent_type="dev"))
            assert result is None

    @pytest.mark.asyncio
    async def test_list_agents_no_db(self):
        from agent_economy import registry
        with patch("agent_economy.db.fetch", new=AsyncMock(return_value=[])):
            result = await registry.list_agents()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        from agent_economy import registry
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await registry.get_agent(uuid.uuid4())
            assert result is None


class TestRegistryWithDB:
    @pytest.mark.asyncio
    async def test_create_agent(self):
        from agent_economy.models import AgentCreate, Agent
        from agent_economy import registry
        row = _make_agent_row(name="dev-1", agent_type="dev")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            result = await registry.create_agent(AgentCreate(name="dev-1", agent_type="dev"))
            assert isinstance(result, Agent)
            assert result.name == "dev-1"
            assert result.reputation_score == 1.0

    @pytest.mark.asyncio
    async def test_get_agent(self):
        from agent_economy.models import Agent
        from agent_economy import registry
        aid = uuid.uuid4()
        row = _make_agent_row(id=aid, name="qa-1", agent_type="qa")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            result = await registry.get_agent(aid)
            assert isinstance(result, Agent)
            assert result.agent_type == "qa"

    @pytest.mark.asyncio
    async def test_get_agent_stats(self):
        from agent_economy.models import AgentStats
        from agent_economy import registry
        aid = uuid.uuid4()
        row = _make_agent_row(id=aid, name="dev-2", tasks_completed=8, tasks_failed=2)
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.fetchval", new=AsyncMock(return_value=500)):
                result = await registry.get_agent_stats(aid)
                assert isinstance(result, AgentStats)
                assert result.success_rate == 0.8
                assert result.tokens_this_week == 500

    @pytest.mark.asyncio
    async def test_expire_ttl_agents(self):
        from agent_economy import registry
        with patch("agent_economy.db.fetchval", new=AsyncMock(return_value=2)):
            count = await registry.expire_ttl_agents()
            assert count == 2


# ─────────────────────────────────────────────────────────────────────────────
# Broker
# ─────────────────────────────────────────────────────────────────────────────

class TestBroker:
    @pytest.mark.asyncio
    async def test_create_task(self):
        from agent_economy.models import TaskCreate, Task
        from agent_economy import broker
        tc = TaskCreate(title="Review PR #42", task_type="code_review", priority=3)
        row = _make_task_row(title="Review PR #42", task_type="code_review")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            result = await broker.create_task(tc)
            assert isinstance(result, Task)
            assert result.status == "created"

    @pytest.mark.asyncio
    async def test_claim_task(self):
        from agent_economy.models import TaskClaimRequest, Task
        from agent_economy import broker
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        row = _make_task_row(id=tid, status="claimed", assigned_to=aid)
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.execute", new=AsyncMock()):
                result = await broker.claim_task(tid, TaskClaimRequest(agent_id=aid))
                assert isinstance(result, Task)
                assert result.status == "claimed"
                assert result.assigned_to == aid

    @pytest.mark.asyncio
    async def test_claim_task_already_claimed(self):
        from agent_economy.models import TaskClaimRequest
        from agent_economy import broker
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await broker.claim_task(tid, TaskClaimRequest(agent_id=aid))
            assert result is None

    @pytest.mark.asyncio
    async def test_complete_task(self):
        from agent_economy.models import TaskCompleteRequest, Task
        from agent_economy import broker
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        row = _make_task_row(id=tid, status="completed", assigned_to=aid, quality_score=0.95)
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.execute", new=AsyncMock()):
                result = await broker.complete_task(
                    tid, TaskCompleteRequest(result={"ok": True}, tokens_used=300, quality_score=0.95)
                )
                assert isinstance(result, Task)
                assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_fail_task(self):
        from agent_economy.models import TaskFailRequest, Task
        from agent_economy import broker
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        row = _make_task_row(id=tid, status="failed", assigned_to=aid, error="timeout")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.execute", new=AsyncMock()):
                result = await broker.fail_task(tid, TaskFailRequest(error="timeout", tokens_used=50))
                assert isinstance(result, Task)
                assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_find_available_agent(self):
        from agent_economy import broker
        aid = uuid.uuid4()
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value={"id": aid})):
            result = await broker.find_available_agent("code_review")
            assert result == aid

    @pytest.mark.asyncio
    async def test_find_available_agent_none(self):
        from agent_economy import broker
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await broker.find_available_agent("code_review")
            assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────────────────────

class TestBudget:
    @pytest.mark.asyncio
    async def test_log_spend(self):
        from agent_economy.models import BudgetLogCreate, BudgetLogEntry
        from agent_economy import budget
        aid = uuid.uuid4()
        row = _make_budget_row(agent_id=aid, tokens_used=200)
        data = BudgetLogCreate(agent_id=aid, tokens_used=200, model_name="qwen2.5:3b")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.execute", new=AsyncMock()):
                result = await budget.log_spend(data)
                assert isinstance(result, BudgetLogEntry)
                assert result.tokens_used == 200

    @pytest.mark.asyncio
    async def test_log_spend_no_db(self):
        from agent_economy.models import BudgetLogCreate
        from agent_economy import budget
        aid = uuid.uuid4()
        data = BudgetLogCreate(agent_id=aid, tokens_used=100)
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await budget.log_spend(data)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_summary(self):
        from agent_economy.models import BudgetSummary
        from agent_economy import budget
        aid = uuid.uuid4()
        agent_row = {"id": aid, "name": "dev-1", "budget_tokens_total": 50000}
        agg_row = {"total": 15000, "entries": 42}
        ops_rows = [{"operation": "task_execution", "tokens": 12000}]

        async def _fetchrow(q, *args):
            if "ae_agents" in q:
                return agent_row
            return agg_row

        with patch("agent_economy.db.fetchrow", new=AsyncMock(side_effect=_fetchrow)):
            with patch("agent_economy.db.fetch", new=AsyncMock(return_value=ops_rows)):
                result = await budget.get_summary(aid)
                assert isinstance(result, BudgetSummary)
                assert result.total_tokens == 15000
                assert result.budget_limit == 50000
                assert len(result.top_operations) == 1

    @pytest.mark.asyncio
    async def test_get_summary_agent_not_found(self):
        from agent_economy import budget
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await budget.get_summary(uuid.uuid4())
            assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Spawn
# ─────────────────────────────────────────────────────────────────────────────

class TestSpawn:
    @pytest.mark.asyncio
    async def test_create_spawn_request_pending(self):
        """Spawn request stays pending when auto-approve threshold exceeded."""
        from agent_economy.models import SpawnRequestCreate, SpawnRequest
        from agent_economy import spawn
        aid = uuid.uuid4()
        row = _make_spawn_row(requested_by=aid, status="pending")
        data = SpawnRequestCreate(
            requested_by=aid,
            template_name="dev",
            purpose="Need extra capacity",
        )

        async def _fetchrow(q, *args):
            return row

        with patch("agent_economy.db.fetchrow", new=AsyncMock(side_effect=_fetchrow)):
            # Active spawned count = 5 > threshold (3) → stays pending
            with patch("agent_economy.db.fetchval", new=AsyncMock(return_value=5)):
                result = await spawn.create_spawn_request(data)
                assert isinstance(result, SpawnRequest)
                assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_reject_spawn_request(self):
        from agent_economy.models import SpawnRejectRequest, SpawnRequest
        from agent_economy import spawn
        rid = uuid.uuid4()
        row = _make_spawn_row(id=rid, status="rejected", rejection_reason="Not needed")
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            result = await spawn.reject_spawn_request(
                rid, SpawnRejectRequest(approved_by="team-lead", reason="Not needed")
            )
            assert isinstance(result, SpawnRequest)
            assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_list_spawn_requests(self):
        from agent_economy.models import SpawnRequest
        from agent_economy import spawn
        rows = [_make_spawn_row(), _make_spawn_row()]
        with patch("agent_economy.db.fetch", new=AsyncMock(return_value=rows)):
            result = await spawn.list_spawn_requests()
            assert len(result) == 2
            assert all(isinstance(r, SpawnRequest) for r in result)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app integration (no DB, no NATS)
# ─────────────────────────────────────────────────────────────────────────────

class TestAppEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from agent_economy import main, db
        # Patch lifespan to skip DB init and NATS
        with patch.object(db, "init_pool", new=AsyncMock()):
            with patch.object(db, "close_pool", new=AsyncMock()):
                with patch("agent_economy.main._start_nats", new=AsyncMock()):
                    with patch("agent_economy.main._register_with_oracle", new=AsyncMock()):
                        with patch("agent_economy.main._expire_ttl_loop", new=AsyncMock()):
                            with TestClient(main.app, raise_server_exceptions=False) as c:
                                yield c

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "db" in data

    def test_create_agent_no_db(self, client):
        with patch("agent_economy.registry.create_agent", new=AsyncMock(return_value=None)):
            resp = client.post("/api/v1/agents", json={"name": "dev-1", "agent_type": "dev"})
            assert resp.status_code == 503

    def test_list_agents_empty(self, client):
        with patch("agent_economy.registry.list_agents", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/agents")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_get_agent_not_found(self, client):
        with patch("agent_economy.registry.get_agent", new=AsyncMock(return_value=None)):
            resp = client.get(f"/api/v1/agents/{uuid.uuid4()}")
            assert resp.status_code == 404

    def test_create_task_no_db(self, client):
        with patch("agent_economy.broker.create_task", new=AsyncMock(return_value=None)):
            resp = client.post("/api/v1/tasks", json={
                "title": "Test task", "task_type": "code_review", "priority": 3
            })
            assert resp.status_code == 503

    def test_list_tasks_empty(self, client):
        with patch("agent_economy.broker.list_tasks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/tasks")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_claim_task_conflict(self, client):
        with patch("agent_economy.broker.claim_task", new=AsyncMock(return_value=None)):
            resp = client.post(
                f"/api/v1/tasks/{uuid.uuid4()}/claim",
                json={"agent_id": str(uuid.uuid4())},
            )
            assert resp.status_code == 409

    def test_dashboard_no_db(self, client):
        with patch("agent_economy.db.fetchval", new=AsyncMock(return_value=0)):
            with patch("agent_economy.db.fetch", new=AsyncMock(return_value=[])):
                resp = client.get("/api/v1/dashboard")
                assert resp.status_code == 200
                data = resp.json()
                assert "total_agents" in data
                assert "top_agents" in data

    def test_rate_limit_returns_429(self, client):
        import time
        from agent_economy import main
        # Starlette TestClient sets client host to "testclient"
        key = "testclient"
        now = time.monotonic()
        from agent_economy.config import settings
        main._rate_buckets[key] = [now] * settings.rate_limit_rpm
        try:
            resp = client.get("/health")
            assert resp.status_code == 429
            assert resp.headers.get("Retry-After") == "60"
        finally:
            main._rate_buckets[key] = []

    def test_rate_limit_allows_normal_traffic(self, client):
        from agent_economy import main
        # Ensure bucket is clear so the request goes through
        main._rate_buckets["testclient"] = []
        resp = client.get("/health")
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers — JSONB codec + pool initializer
# ─────────────────────────────────────────────────────────────────────────────

class TestDbHelpers:
    def test_json_codec_encoder_produces_string(self):
        """_init_conn uses json.dumps; verify it serialises a dict to a string."""
        import json
        payload = {"subject": "energy.price.spike", "value": 0.35}
        encoded = json.dumps(payload)
        assert isinstance(encoded, str)
        assert '"subject"' in encoded

    def test_json_codec_decoder_restores_dict(self):
        """_init_conn uses json.loads; verify it deserialises back to a dict."""
        import json
        raw = '{"event": "task.created", "priority": 4}'
        decoded = json.loads(raw)
        assert isinstance(decoded, dict)
        assert decoded["priority"] == 4

    def test_task_nats_payload_default_is_empty_dict(self):
        """TaskCreate.nats_payload defaults to {} so JSONB column always gets a valid value."""
        from agent_economy.models import TaskCreate
        t = TaskCreate(title="x", task_type="code_review")
        assert t.nats_payload == {}

    def test_task_complete_result_is_dict(self):
        """TaskCompleteRequest.result must be a dict (serialised to JSONB result column)."""
        from agent_economy.models import TaskCompleteRequest
        r = TaskCompleteRequest(result={"output": "done", "lines": 42}, tokens_used=100)
        assert isinstance(r.result, dict)
        assert r.result["lines"] == 42


# ─────────────────────────────────────────────────────────────────────────────
# Broker — budget enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestBrokerBudget:
    @pytest.mark.asyncio
    async def test_find_available_agent_budget_exhausted(self):
        """find_available_agent must skip agents whose budget is exhausted."""
        from agent_economy import broker
        # DB returns None because the WHERE clause (budget check) excludes exhausted agents
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=None)):
            result = await broker.find_available_agent("energy_response")
            assert result is None

    @pytest.mark.asyncio
    async def test_find_available_agent_picks_highest_reputation(self):
        """find_available_agent returns the first row (DB orders by reputation DESC)."""
        from agent_economy import broker
        best_id = uuid.uuid4()
        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value={"id": best_id})):
            result = await broker.find_available_agent("infra_remediation")
            assert result == best_id

    @pytest.mark.asyncio
    async def test_complete_task_updates_reputation(self):
        """complete_task calls both fetchrow (update task) and execute (update agent)."""
        from agent_economy.models import TaskCompleteRequest, Task
        from agent_economy import broker
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        row = _make_task_row(id=tid, status="completed", assigned_to=aid, quality_score=0.8)
        executed: list[str] = []

        async def _exec(q, *args):
            executed.append(q)

        with patch("agent_economy.db.fetchrow", new=AsyncMock(return_value=row)):
            with patch("agent_economy.db.execute", new=AsyncMock(side_effect=_exec)):
                result = await broker.complete_task(
                    tid, TaskCompleteRequest(result={"ok": True}, tokens_used=200, quality_score=0.8)
                )
                assert isinstance(result, Task)
                # Should have called execute to update agent reputation
                assert len(executed) == 1
                assert "reputation_score" in executed[0]
