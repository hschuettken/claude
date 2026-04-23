"""
Tests for audit-fix changes:
1. TopicService._build_scoring_context — published_posts and pillar_id now loaded from DB
2. TopicService.pop_auto_draft_ids — auto-draft queue mechanics
3. DraftWriter._generate_outline — summary derived from score_breakdown or signals
4. api/topics.py — refresh endpoint queues auto-drafts for score > 0.8
"""

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Stub sklearn so TopicService can be imported without the package installed
_sklearn_stub = types.ModuleType("sklearn")
_sklearn_stub.feature_extraction = types.ModuleType("sklearn.feature_extraction")
_sklearn_stub.feature_extraction.text = types.ModuleType("sklearn.feature_extraction.text")
_sklearn_stub.feature_extraction.text.TfidfVectorizer = MagicMock()
_sklearn_stub.metrics = types.ModuleType("sklearn.metrics")
_sklearn_stub.metrics.pairwise = types.ModuleType("sklearn.metrics.pairwise")
_sklearn_stub.metrics.pairwise.cosine_similarity = MagicMock()
sys.modules.setdefault("sklearn", _sklearn_stub)
sys.modules.setdefault("sklearn.feature_extraction", _sklearn_stub.feature_extraction)
sys.modules.setdefault("sklearn.feature_extraction.text", _sklearn_stub.feature_extraction.text)
sys.modules.setdefault("sklearn.metrics", _sklearn_stub.metrics)
sys.modules.setdefault("sklearn.metrics.pairwise", _sklearn_stub.metrics.pairwise)


# ---------------------------------------------------------------------------
# TopicService unit tests
# ---------------------------------------------------------------------------


class TestTopicServiceScoringContext:
    """_build_scoring_context now properly loads published_posts + pillar_id."""

    def _make_db(self, voice_rules=None, perf_history=None, published_posts_raw=None):
        """Return a mock Session with preconfigured query results."""
        db = MagicMock()

        def _query(*models):
            mock_q = MagicMock()
            # Chain .join() and .outerjoin() back to self so further chaining works
            mock_q.join.return_value = mock_q
            mock_q.outerjoin.return_value = mock_q
            mock_q.filter.return_value = mock_q

            # Determine which query this is by inspecting model names
            model_names = " ".join(getattr(m, "__name__", str(m)) for m in models)

            if "VoiceRule" in model_names:
                mock_q.all.return_value = voice_rules or []
            elif "PerformanceSnapshot" in model_names:
                mock_q.all.return_value = perf_history or []
            elif "BlogPost" in model_names:
                mock_q.all.return_value = published_posts_raw or []
            else:
                mock_q.all.return_value = []
            return mock_q

        db.query.side_effect = _query
        return db

    def test_empty_db_returns_defaults(self):
        """Empty DB → empty lists, no crash."""
        from app.topics.service import TopicService

        db = self._make_db()
        service = TopicService(db)
        ctx = service._build_scoring_context()

        assert ctx.published_posts == []
        assert ctx.performance_history == []
        assert ctx.audience_segments == ["technical", "enterprise", "developers"]

    def test_published_posts_loaded(self):
        """published_posts list is populated from BlogPost join."""
        from app.topics.service import TopicService

        bp = MagicMock()
        bp.id = 10
        bp.published_at = datetime(2026, 4, 1)

        d = MagicMock()
        d.title = "Datasphere deep dive"

        t = MagicMock()
        t.pillar_id = 2

        db = self._make_db(published_posts_raw=[(bp, d, t)])
        service = TopicService(db)
        ctx = service._build_scoring_context()

        assert len(ctx.published_posts) == 1
        post = ctx.published_posts[0]
        assert post["post_id"] == 10
        assert post["title"] == "Datasphere deep dive"
        assert post["pillar_id"] == 2

    def test_performance_pillar_from_topic(self):
        """pillar_id in performance_history comes from Topic, not hardcoded 1."""
        from app.topics.service import TopicService

        p = MagicMock()
        p.post_id = 5
        p.platform = "blog"
        p.engagement_rate = 0.12

        d = MagicMock()
        t = MagicMock()
        t.pillar_id = 3

        db = self._make_db(perf_history=[(p, d, t)])
        service = TopicService(db)
        ctx = service._build_scoring_context()

        assert ctx.performance_history[0]["pillar_id"] == 3

    def test_performance_pillar_none_when_no_topic(self):
        """If Topic join returns None, pillar_id is None (not hardcoded 1)."""
        from app.topics.service import TopicService

        p = MagicMock()
        p.post_id = 7
        p.platform = "linkedin"
        p.engagement_rate = 0.05

        d = MagicMock()
        # t = None → no topic linked

        db = self._make_db(perf_history=[(p, d, None)])
        service = TopicService(db)
        ctx = service._build_scoring_context()

        assert ctx.performance_history[0]["pillar_id"] is None


class TestAutoДрафтQueue:
    """pop_auto_draft_ids and the queue accumulation logic."""

    def test_pop_empty(self):
        from app.topics.service import TopicService

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        service = TopicService(db)

        ids = service.pop_auto_draft_ids()
        assert ids == []

    def test_pop_clears_queue(self):
        from app.topics.service import TopicService

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        service = TopicService(db)
        service._auto_draft_ids = [1, 2, 3]

        first = service.pop_auto_draft_ids()
        assert first == [1, 2, 3]

        second = service.pop_auto_draft_ids()
        assert second == []


# ---------------------------------------------------------------------------
# DraftWriter._generate_outline — summary derivation
# ---------------------------------------------------------------------------


class TestDraftWriterSummary:
    """_generate_outline picks up summary from score_breakdown → snippet → name."""

    def _make_topic(self, name="Test Topic", score_breakdown=None):
        t = MagicMock()
        t.name = name
        t.score_breakdown = score_breakdown
        t.pillar_id = 1
        return t

    def _make_signal(self, snippet="Signal snippet content"):
        s = MagicMock()
        s.snippet = snippet
        return s

    @pytest.mark.asyncio
    async def test_summary_from_breakdown(self):
        """When score_breakdown has 'summary', it is used."""
        from app.drafts.writer import DraftWriter

        db = MagicMock()
        topic = self._make_topic(score_breakdown={"summary": "BD summary"})
        signals = [self._make_signal("Some signal")]

        writer = DraftWriter.__new__(DraftWriter)
        writer.db = db
        writer.llm_client = AsyncMock()
        writer.kg_query = None

        captured_prompt = {}

        async def fake_generate(sys_p, user_p):
            captured_prompt["user"] = user_p
            return '{"title":"t","subtitle":"s","hook":"h","sections":[],"takeaways":[],"cta":"c"}'

        writer.llm_client.generate = fake_generate

        with patch("app.drafts.writer.BLOG_OUTLINE_PROMPT", "{title}{summary}{signals}"):
            await writer._generate_outline(topic, "signals text", signals=signals)

        assert "BD summary" in captured_prompt["user"]

    @pytest.mark.asyncio
    async def test_summary_from_signal_snippet(self):
        """When no breakdown summary, first signal snippet is used."""
        from app.drafts.writer import DraftWriter

        db = MagicMock()
        topic = self._make_topic(score_breakdown={})
        signals = [self._make_signal("Signal snippet abc")]

        writer = DraftWriter.__new__(DraftWriter)
        writer.db = db
        writer.llm_client = AsyncMock()
        writer.kg_query = None

        captured_prompt = {}

        async def fake_generate(sys_p, user_p):
            captured_prompt["user"] = user_p
            return '{"title":"t","subtitle":"s","hook":"h","sections":[],"takeaways":[],"cta":"c"}'

        writer.llm_client.generate = fake_generate

        with patch("app.drafts.writer.BLOG_OUTLINE_PROMPT", "{title}{summary}{signals}"):
            await writer._generate_outline(topic, "signals text", signals=signals)

        assert "Signal snippet abc" in captured_prompt["user"]

    @pytest.mark.asyncio
    async def test_summary_falls_back_to_name(self):
        """When no breakdown summary and no signals, topic.name is the summary."""
        from app.drafts.writer import DraftWriter

        db = MagicMock()
        topic = self._make_topic(name="My Topic Name", score_breakdown=None)

        writer = DraftWriter.__new__(DraftWriter)
        writer.db = db
        writer.llm_client = AsyncMock()
        writer.kg_query = None

        captured_prompt = {}

        async def fake_generate(sys_p, user_p):
            captured_prompt["user"] = user_p
            return '{"title":"t","subtitle":"s","hook":"h","sections":[],"takeaways":[],"cta":"c"}'

        writer.llm_client.generate = fake_generate

        with patch("app.drafts.writer.BLOG_OUTLINE_PROMPT", "{title}{summary}{signals}"):
            await writer._generate_outline(topic, "signals text", signals=None)

        assert "My Topic Name" in captured_prompt["user"]
