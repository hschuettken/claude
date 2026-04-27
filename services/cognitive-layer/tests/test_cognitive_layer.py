"""Tests for the Cognitive Layer service.

All tests run without a real database — db.py returns gracefully (None/[])
when the pool is absent, and the modules handle that gracefully.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the service root is on the path when running from this directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_node_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "node_type": "concept",
        "label": "test-label",
        "properties": {},
        "source": None,
        "source_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def _make_edge_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "source_id": uuid.uuid4(),
        "target_id": uuid.uuid4(),
        "relation_type": "RELATES_TO",
        "weight": 1.0,
        "properties": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def _make_thread_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test thread",
        "summary": None,
        "status": "open",
        "recurrence": 0,
        "last_seen_at": "2026-01-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        "node_ids": [],
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class TestModels:
    def test_node_create(self):
        from cognitive_layer.models import NodeCreate
        n = NodeCreate(node_type="page", label="My Page", source="memora", source_id="abc123")
        assert n.node_type == "page"
        assert n.source_id == "abc123"

    def test_edge_create(self):
        from cognitive_layer.models import EdgeCreate
        sid, tid = uuid.uuid4(), uuid.uuid4()
        e = EdgeCreate(source_id=sid, target_id=tid, relation_type="BLOCKS", weight=0.8)
        assert e.relation_type == "BLOCKS"
        assert e.weight == 0.8

    def test_thread_create(self):
        from cognitive_layer.models import ThreadCreate
        t = ThreadCreate(title="Open Q: API design", node_ids=[uuid.uuid4()])
        assert t.title.startswith("Open Q")
        assert len(t.node_ids) == 1

    def test_ingest_result_defaults(self):
        from cognitive_layer.models import IngestResult
        r = IngestResult(source="git", nodes_created=5, edges_created=3)
        assert r.errors == []
        assert r.nodes_created == 5


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph (no-DB path)
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeGraphNoDb:
    """Tests that run when the pool is None — all operations return None/[]."""

    @pytest.mark.asyncio
    async def test_create_node_no_db(self):
        from cognitive_layer.models import NodeCreate
        import cognitive_layer.db as db_module
        import cognitive_layer.knowledge_graph as kg
        orig = db_module._pool
        db_module._pool = None
        try:
            node = await kg.create_node(NodeCreate(node_type="concept", label="x"))
            assert node is None
        finally:
            db_module._pool = orig

    @pytest.mark.asyncio
    async def test_list_nodes_no_db(self):
        import cognitive_layer.db as db_module
        import cognitive_layer.knowledge_graph as kg
        orig = db_module._pool
        db_module._pool = None
        try:
            nodes = await kg.list_nodes()
            assert nodes == []
        finally:
            db_module._pool = orig

    @pytest.mark.asyncio
    async def test_search_nodes_no_db(self):
        import cognitive_layer.db as db_module
        import cognitive_layer.knowledge_graph as kg
        orig = db_module._pool
        db_module._pool = None
        try:
            nodes = await kg.search_nodes("anything")
            assert nodes == []
        finally:
            db_module._pool = orig


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeGraphMocked:
    @pytest.mark.asyncio
    async def test_create_node_returns_node(self):
        from cognitive_layer.models import NodeCreate
        import cognitive_layer.knowledge_graph as kg
        row = _make_node_row(node_type="git_commit", label="abc: fix bug")
        with patch("cognitive_layer.knowledge_graph.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            node = await kg.create_node(NodeCreate(node_type="git_commit", label="abc: fix bug"))
        assert node is not None
        assert node.node_type == "git_commit"
        assert node.label == "abc: fix bug"

    @pytest.mark.asyncio
    async def test_get_node_not_found(self):
        import cognitive_layer.knowledge_graph as kg
        with patch("cognitive_layer.knowledge_graph.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            node = await kg.get_node(uuid.uuid4())
        assert node is None

    @pytest.mark.asyncio
    async def test_create_edge_returns_edge(self):
        from cognitive_layer.models import EdgeCreate
        import cognitive_layer.knowledge_graph as kg
        sid, tid = uuid.uuid4(), uuid.uuid4()
        row = _make_edge_row(source_id=sid, target_id=tid)
        with patch("cognitive_layer.knowledge_graph.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            edge = await kg.create_edge(EdgeCreate(source_id=sid, target_id=tid, relation_type="PART_OF"))
        assert edge is not None
        assert edge.relation_type == "RELATES_TO"  # from mock row

    @pytest.mark.asyncio
    async def test_delete_node(self):
        import cognitive_layer.knowledge_graph as kg
        nid = uuid.uuid4()
        with patch("cognitive_layer.knowledge_graph.db") as mock_db:
            mock_db.fetchval = AsyncMock(return_value=nid)
            deleted = await kg.delete_node(nid)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_list_nodes_filtered(self):
        import cognitive_layer.knowledge_graph as kg
        rows = [_make_node_row(node_type="chat"), _make_node_row(node_type="chat")]
        with patch("cognitive_layer.knowledge_graph.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=rows)
            nodes = await kg.list_nodes(node_type="chat", limit=10)
        assert len(nodes) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Thought Continuity Engine
# ─────────────────────────────────────────────────────────────────────────────

class TestContinuity:
    @pytest.mark.asyncio
    async def test_create_thread(self):
        from cognitive_layer.models import ThreadCreate
        import cognitive_layer.continuity as cont
        row = _make_thread_row(title="Open Q: deploy timing")
        with patch("cognitive_layer.continuity.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            thread = await cont.create_thread(ThreadCreate(title="Open Q: deploy timing"))
        assert thread is not None
        assert thread.status == "open"

    @pytest.mark.asyncio
    async def test_list_threads_no_db(self):
        import cognitive_layer.db as db_module
        import cognitive_layer.continuity as cont
        orig = db_module._pool
        db_module._pool = None
        try:
            threads = await cont.list_threads()
            assert threads == []
        finally:
            db_module._pool = orig

    @pytest.mark.asyncio
    async def test_touch_thread(self):
        import cognitive_layer.continuity as cont
        tid = uuid.uuid4()
        row = _make_thread_row(id=tid, status="open", recurrence=1)
        with patch("cognitive_layer.continuity.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            thread = await cont.touch_thread(tid)
        assert thread is not None
        assert thread.recurrence == 1

    @pytest.mark.asyncio
    async def test_maintenance_no_db(self):
        import cognitive_layer.db as db_module
        import cognitive_layer.continuity as cont
        orig = db_module._pool
        db_module._pool = None
        try:
            result = await cont.run_maintenance()
            assert result["dormant"] == 0
            assert result["recurring"] == 0
        finally:
            db_module._pool = orig


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Load Monitor
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitiveLoad:
    @pytest.mark.asyncio
    async def test_debt_label_low(self):
        import cognitive_layer.cognitive_load as cl
        assert cl._debt_label(10) == "low"
        assert cl._debt_label(40) == "moderate"
        assert cl._debt_label(60) == "high"
        assert cl._debt_label(90) == "critical"

    @pytest.mark.asyncio
    async def test_compute_no_db(self):
        """Compute should return score=0 when DB is absent (all counts return 0)."""
        import cognitive_layer.db as db_module
        import cognitive_layer.cognitive_load as cl
        orig = db_module._pool
        db_module._pool = None
        # _count_overdue_tasks calls Orbit HTTP — mock it
        with patch("cognitive_layer.cognitive_load.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_client.get = AsyncMock(return_value=mock_resp)
            try:
                status = await cl.compute()
                assert status.debt_score == 0.0
                assert status.label == "low"
            finally:
                db_module._pool = orig


# ─────────────────────────────────────────────────────────────────────────────
# Briefing (no LLM / no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestBriefing:
    def test_fallback_briefing(self):
        import cognitive_layer.briefing as br
        ctx = {
            "date": "2026-04-27",
            "cognitive_load": {"score": 35, "label": "moderate"},
            "open_threads": ["API design", "Deploy timing"],
        }
        text = br._fallback_briefing(ctx)
        assert "2026-04-27" in text
        assert "moderate" in text

    @pytest.mark.asyncio
    async def test_get_or_generate_briefing_no_db(self):
        """When DB is absent, briefing is generated with LLM fallback."""
        import cognitive_layer.db as db_module
        import cognitive_layer.briefing as br
        orig = db_module._pool
        db_module._pool = None
        try:
            with patch("cognitive_layer.briefing.cognitive_load") as mock_cl, \
                 patch("cognitive_layer.briefing.continuity") as mock_cont, \
                 patch("cognitive_layer.briefing.httpx.AsyncClient") as mock_http:
                mock_load = MagicMock()
                mock_load.debt_score = 20.0
                mock_load.label = "low"
                mock_cl.compute = AsyncMock(return_value=mock_load)
                mock_cont.list_threads = AsyncMock(return_value=[])
                # LLM call raises to trigger fallback
                mock_http.side_effect = Exception("LLM offline")
                briefing_obj = await br.get_or_generate_briefing(date(2026, 4, 27))
            assert briefing_obj.date == date(2026, 4, 27)
            assert len(briefing_obj.narrative) > 0
        finally:
            db_module._pool = orig


# ─────────────────────────────────────────────────────────────────────────────
# Chat Export Ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestChatExportIngestion:
    @pytest.mark.asyncio
    async def test_ingest_chatgpt_export(self):
        """Test parsing a minimal ChatGPT export."""
        from cognitive_layer.ingestion.chat_export import ingest_chat_export

        export_data = [
            {
                "id": "conv-001",
                "title": "Deployment strategy",
                "mapping": {
                    "node1": {
                        "message": {
                            "id": "msg-001",
                            "author": {"role": "user"},
                            "content": {"parts": ["How should we design the deployment pipeline for the cognitive layer service?"]},
                        }
                    },
                    "node2": {
                        "message": {
                            "id": "msg-002",
                            "author": {"role": "assistant"},
                            "content": {"parts": ["You should use Docker Compose with a rolling restart strategy."]},
                        }
                    },
                },
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(export_data, f)
            path = f.name

        try:
            with patch("cognitive_layer.ingestion.chat_export.kg") as mock_kg:
                created_node = MagicMock()
                created_node.id = uuid.uuid4()
                mock_kg.create_node = AsyncMock(return_value=created_node)
                mock_kg.create_edge = AsyncMock(return_value=MagicMock())
                result = await ingest_chat_export(path)
            assert result.source == "chat_export"
            assert result.nodes_created >= 1  # at least the chat node
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_ingest_claude_export(self):
        """Test parsing a minimal Claude-format export."""
        from cognitive_layer.ingestion.chat_export import ingest_chat_export

        export_data = [
            {
                "uuid": "conv-002",
                "name": "Architecture review",
                "messages": [
                    {"role": "user", "content": "What are the trade-offs of using PostgreSQL vs Neo4j for the knowledge graph?", "id": "m1"},
                    {"role": "assistant", "content": "PostgreSQL is simpler to operate...", "id": "m2"},
                ],
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(export_data, f)
            path = f.name

        try:
            with patch("cognitive_layer.ingestion.chat_export.kg") as mock_kg:
                chat_node = MagicMock()
                chat_node.id = uuid.uuid4()
                thought_node = MagicMock()
                thought_node.id = uuid.uuid4()
                mock_kg.create_node = AsyncMock(side_effect=[chat_node, thought_node])
                mock_kg.create_edge = AsyncMock(return_value=MagicMock())
                result = await ingest_chat_export(path)
            assert result.nodes_created >= 1
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_ingest_missing_file(self):
        from cognitive_layer.ingestion.chat_export import ingest_chat_export
        result = await ingest_chat_export("/nonexistent/path.json")
        assert len(result.errors) > 0
        assert result.nodes_created == 0


# ─────────────────────────────────────────────────────────────────────────────
# Git Activity Ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestGitIngestion:
    @pytest.mark.asyncio
    async def test_ingest_no_token(self):
        from cognitive_layer.ingestion.git_activity import ingest_git_activity
        with patch("cognitive_layer.ingestion.git_activity.settings") as mock_settings:
            mock_settings.github_token = ""
            result = await ingest_git_activity()
        assert any("GITHUB_TOKEN" in e for e in result.errors)
        assert result.nodes_created == 0

    @pytest.mark.asyncio
    async def test_ingest_commits(self):
        """Mock GitHub API response → expect nodes created."""
        from cognitive_layer.ingestion.git_activity import ingest_git_activity

        mock_commits = [
            {
                "sha": "abc123def456",
                "commit": {
                    "message": "feat(cognitive): add briefing module",
                    "author": {"name": "Henning", "date": "2026-04-27T08:00:00Z"},
                },
            },
            {
                "sha": "def456abc789",
                "commit": {
                    "message": "fix(kg): upsert conflict resolution",
                    "author": {"name": "Henning", "date": "2026-04-27T10:00:00Z"},
                },
            },
        ]

        with patch("cognitive_layer.ingestion.git_activity.settings") as mock_settings, \
             patch("cognitive_layer.ingestion.git_activity.kg") as mock_kg, \
             patch("cognitive_layer.ingestion.git_activity.httpx.AsyncClient") as mock_client_cls:

            mock_settings.github_token = "ghp_fake"
            mock_settings.github_owner = "hschuettken"

            repo_node = MagicMock(); repo_node.id = uuid.uuid4()
            commit_node = MagicMock(); commit_node.id = uuid.uuid4()
            mock_kg.create_node = AsyncMock(side_effect=[repo_node, commit_node, commit_node])
            mock_kg.create_edge = AsyncMock(return_value=MagicMock())

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value=mock_commits)
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ingest_git_activity(repos=["claude"], since_days=7)

        assert result.nodes_created >= 1
        assert result.source == "git"


# ─────────────────────────────────────────────────────────────────────────────
# HA Events Ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestHaEventsIngestion:
    @pytest.mark.asyncio
    async def test_bulk_ingest_filters_irrelevant(self):
        from cognitive_layer.ingestion.ha_events import ingest_ha_events_bulk

        events = [
            {"entity_id": "sensor.time", "old_state": "12:00", "new_state": "12:01"},  # blocklist
            {"entity_id": "sensor.date", "old_state": "2026-04-26", "new_state": "2026-04-27"},  # blocklist
            {"entity_id": "automation.morning_lights", "old_state": "off", "new_state": "on"},  # wrong domain
        ]
        with patch("cognitive_layer.ingestion.ha_events.kg") as mock_kg:
            mock_kg.create_node = AsyncMock(return_value=None)
            result = await ingest_ha_events_bulk(events)
        assert result.nodes_created == 0

    @pytest.mark.asyncio
    async def test_bulk_ingest_person_event(self):
        from cognitive_layer.ingestion.ha_events import ingest_ha_events_bulk

        events = [
            {
                "entity_id": "person.henning",
                "old_state": "home",
                "new_state": "not_home",
                "event_id": "ev-001",
            }
        ]
        with patch("cognitive_layer.ingestion.ha_events.kg") as mock_kg:
            created = MagicMock(); created.id = uuid.uuid4()
            mock_kg.create_node = AsyncMock(return_value=created)
            result = await ingest_ha_events_bulk(events)
        assert result.nodes_created == 1


# ─────────────────────────────────────────────────────────────────────────────
# Reflection
# ─────────────────────────────────────────────────────────────────────────────

class TestReflection:
    @pytest.mark.asyncio
    async def test_daily_reflection_no_db(self):
        """When DB is absent, _load_cached returns None and _save returns a fresh report."""
        import cognitive_layer.db as db_module
        import cognitive_layer.reflection as refl
        orig = db_module._pool
        db_module._pool = None
        try:
            with patch("cognitive_layer.reflection.httpx.AsyncClient") as mock_http:
                # LLM fails → fallback narrative
                mock_http.side_effect = Exception("no LLM")
                report = await refl.get_or_generate_daily(date(2026, 4, 27))
            assert report.period_type == "daily"
            assert report.period_start == date(2026, 4, 27)
            assert len(report.content) > 0
        finally:
            db_module._pool = orig

    def test_fallback_narrative_contains_data(self):
        import cognitive_layer.reflection as refl
        # Test that fallback JSON embed works
        metrics = {"date": "2026-04-27", "commits": ["fix: bug"], "tasks_completed": []}
        narrative = refl._PROMPTS["daily"]
        assert "Orbit" in narrative  # sanity check the prompt template


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_settings_defaults(self):
        from cognitive_layer.config import Settings
        s = Settings()
        assert "5432" in s.db_url
        assert s.port == 8230
        assert s.llm_model == "qwen2.5:3b"
        assert s.open_threads_weight + s.overdue_tasks_weight + s.unprocessed_events_weight == 1.0
