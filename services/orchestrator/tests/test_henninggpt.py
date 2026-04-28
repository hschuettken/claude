"""Tests for HenningGPT Personal AI Model — FR #42.

Covers all four phases:
  Phase 1 — Decision memory RAG  (DecisionMemory)
  Phase 2 — Preference graph     (PreferenceGraph + persona selection)
  Phase 3 — Active learning      (LearningLoop + AccuracyReport)
  Phase 4 — Delegation mode      (DelegationEngine + DelegationDecision)
  Router  — henninggpt_router endpoints

All external dependencies (Postgres pool) are mocked with AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_pool(fetch_results=None, fetchrow_result=None):
    """Create a minimal asyncpg Pool mock."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch_results or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_decision_row(
    decision_id=None,
    user_id="henning",
    context="charging EV overnight",
    decision="charge to 80%",
    reasoning="enough range for tomorrow",
    outcome="correct",
    tags=None,
    confidence=0.85,
):
    """Build a dict mimicking an asyncpg Record for a decisions row."""
    return {
        "id": decision_id or str(uuid4()),
        "user_id": user_id,
        "context": context,
        "decision": decision,
        "reasoning": reasoning,
        "outcome": outcome,
        "tags": "[]" if tags is None else __import__("json").dumps(tags),
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_preference_row(
    node_id=None,
    user_id="henning",
    key="ev_charge_limit",
    value="80%",
    context="energy",
    why="enough for daily commute",
    evidence=None,
    confidence=0.9,
    times_confirmed=3,
):
    return {
        "id": node_id or str(uuid4()),
        "user_id": user_id,
        "key": key,
        "value": value,
        "context": context,
        "why": why,
        "evidence": "[]" if evidence is None else __import__("json").dumps(evidence),
        "confidence": confidence,
        "times_confirmed": times_confirmed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_prediction_row(
    pred_id=None,
    user_id="henning",
    context="EV should charge tonight",
    prediction="charge to 80%",
    confidence=0.85,
    category="energy",
    feedback_correct=None,
):
    return {
        "id": pred_id or str(uuid4()),
        "user_id": user_id,
        "context": context,
        "prediction": prediction,
        "confidence": confidence,
        "category": category,
        "feedback_correct": feedback_correct,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ===========================================================================
# Phase 1 — DecisionMemory
# ===========================================================================


@pytest.mark.asyncio
async def test_decision_memory_store_returns_id():
    """DecisionMemory.store() calls INSERT and returns a UUID string."""
    from companion.decision_memory import DecisionMemory

    pool, conn = _make_pool()
    mem = DecisionMemory(pool)

    decision_id = await mem.store(
        user_id="henning",
        context="EV battery at 30%",
        decision="charge to 80%",
        reasoning="long drive tomorrow",
    )

    assert isinstance(decision_id, str) and len(decision_id) == 36
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_decision_memory_search_scores_by_overlap():
    """DecisionMemory.search() returns entries ranked by keyword overlap."""
    from companion.decision_memory import DecisionMemory

    rows = [
        _make_decision_row(decision="charge EV to 80%", context="battery low"),
        _make_decision_row(decision="set heating to 20°C", context="cold morning"),
    ]
    pool, _ = _make_pool(fetch_results=rows)
    mem = DecisionMemory(pool)

    results = await mem.search(query="charge EV battery")
    assert len(results) >= 1
    # EV/battery row should rank above heating row
    assert "charge" in results[0].decision.lower() or "charge" in results[0].context.lower()


@pytest.mark.asyncio
async def test_decision_memory_search_empty_returns_empty():
    """search() with no stored decisions returns an empty list."""
    from companion.decision_memory import DecisionMemory

    pool, _ = _make_pool(fetch_results=[])
    mem = DecisionMemory(pool)

    results = await mem.search(query="anything")
    assert results == []


@pytest.mark.asyncio
async def test_decision_memory_get_recent():
    """get_recent() returns a list of DecisionEntry objects."""
    from companion.decision_memory import DecisionMemory

    rows = [_make_decision_row() for _ in range(3)]
    pool, _ = _make_pool(fetch_results=rows)
    mem = DecisionMemory(pool)

    entries = await mem.get_recent(user_id="henning", limit=3)
    assert len(entries) == 3
    assert all(e.user_id == "henning" for e in entries)


@pytest.mark.asyncio
async def test_decision_memory_update_outcome():
    """update_outcome() executes an UPDATE on the decisions table."""
    from companion.decision_memory import DecisionMemory

    pool, conn = _make_pool()
    mem = DecisionMemory(pool)

    await mem.update_outcome(decision_id="d1", outcome="plan worked")
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "UPDATE" in call_args[0]


@pytest.mark.asyncio
async def test_decision_memory_to_rag_block():
    """to_rag_block() returns a non-empty string when matches exist."""
    from companion.decision_memory import DecisionMemory

    row = _make_decision_row(
        decision="charge EV to 80%",
        context="battery at 30%",
        reasoning="long trip tomorrow",
    )
    pool, _ = _make_pool(fetch_results=[row])
    mem = DecisionMemory(pool)

    block = await mem.to_rag_block(query="EV charge battery")
    assert "Past Decisions" in block
    assert "charge EV" in block


# ===========================================================================
# Phase 2 — PreferenceGraph + multi-context persona selection
# ===========================================================================


@pytest.mark.asyncio
async def test_preference_graph_upsert_insert():
    """upsert() calls INSERT when no existing row is found."""
    from companion.preference_graph import PreferenceGraph

    pool, conn = _make_pool(fetchrow_result=None)
    graph = PreferenceGraph(pool)

    node_id = await graph.upsert(
        user_id="henning",
        key="ev_charge_limit",
        value="80%",
        context="energy",
        why="sufficient range without stressing battery",
    )

    assert isinstance(node_id, str) and len(node_id) == 36
    # Should have called fetchrow (check) + execute (INSERT)
    conn.fetchrow.assert_called_once()
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_preference_graph_upsert_update():
    """upsert() calls UPDATE when an existing row is found."""
    from companion.preference_graph import PreferenceGraph

    existing_id = str(uuid4())
    pool, conn = _make_pool(fetchrow_result={"id": existing_id})
    graph = PreferenceGraph(pool)

    node_id = await graph.upsert(
        user_id="henning",
        key="ev_charge_limit",
        value="90%",
        context="energy",
    )

    assert node_id == existing_id
    conn.execute.assert_called_once()
    call_sql = conn.execute.call_args[0][0]
    assert "UPDATE" in call_sql


@pytest.mark.asyncio
async def test_preference_graph_confirm():
    """confirm() executes an UPDATE incrementing times_confirmed."""
    from companion.preference_graph import PreferenceGraph

    pool, conn = _make_pool()
    graph = PreferenceGraph(pool)

    await graph.confirm(user_id="henning", key="ev_charge_limit", context="energy")

    conn.execute.assert_called_once()
    call_sql = conn.execute.call_args[0][0]
    assert "times_confirmed" in call_sql


@pytest.mark.asyncio
async def test_preference_graph_query_returns_nodes():
    """query() deserialises rows into PreferenceNode objects."""
    from companion.preference_graph import PreferenceGraph, PreferenceNode

    rows = [_make_preference_row(), _make_preference_row(key="sauna_days", value="tue,fri")]
    pool, _ = _make_pool(fetch_results=rows)
    graph = PreferenceGraph(pool)

    nodes = await graph.query(user_id="henning")
    assert len(nodes) == 2
    assert all(isinstance(n, PreferenceNode) for n in nodes)


@pytest.mark.asyncio
async def test_preference_graph_query_with_context_filter():
    """query(context=...) passes the context param to SQL."""
    from companion.preference_graph import PreferenceGraph

    pool, conn = _make_pool(fetch_results=[])
    graph = PreferenceGraph(pool)

    await graph.query(user_id="henning", context="energy")
    call_args = conn.fetch.call_args[0]
    assert "context" in call_args[0]


@pytest.mark.asyncio
async def test_preference_graph_select_persona_context_energy():
    """select_persona_context() returns 'energy' for EV-related messages."""
    from companion.preference_graph import PreferenceGraph

    pool, _ = _make_pool()
    graph = PreferenceGraph(pool)

    ctx = await graph.select_persona_context(
        user_id="henning",
        message="should I charge the EV tonight?",
    )
    assert ctx == "energy"


@pytest.mark.asyncio
async def test_preference_graph_select_persona_context_work():
    """select_persona_context() returns 'work' for dev-related messages."""
    from companion.preference_graph import PreferenceGraph

    pool, _ = _make_pool()
    graph = PreferenceGraph(pool)

    ctx = await graph.select_persona_context(
        user_id="henning",
        message="deploy the new build and run tests",
    )
    assert ctx == "work"


@pytest.mark.asyncio
async def test_preference_graph_select_persona_context_general_fallback():
    """select_persona_context() falls back to 'general' for unrecognised messages."""
    from companion.preference_graph import PreferenceGraph

    pool, _ = _make_pool()
    graph = PreferenceGraph(pool)

    ctx = await graph.select_persona_context(
        user_id="henning",
        message="what time is it?",
    )
    assert ctx == "general"


@pytest.mark.asyncio
async def test_preference_graph_to_prompt_block():
    """to_prompt_block() returns a non-empty Markdown block."""
    from companion.preference_graph import PreferenceGraph

    rows = [_make_preference_row(why="battery health")]
    pool, _ = _make_pool(fetch_results=rows)
    graph = PreferenceGraph(pool)

    block = await graph.to_prompt_block(user_id="henning", context="energy")
    assert "Preferences" in block
    assert "ev_charge_limit" in block
    assert "battery health" in block


@pytest.mark.asyncio
async def test_preference_graph_to_prompt_block_empty():
    """to_prompt_block() returns empty string when no preferences exist."""
    from companion.preference_graph import PreferenceGraph

    pool, _ = _make_pool(fetch_results=[])
    graph = PreferenceGraph(pool)

    block = await graph.to_prompt_block(user_id="henning")
    assert block == ""


# ===========================================================================
# Phase 3 — LearningLoop + AccuracyReport
# ===========================================================================


@pytest.mark.asyncio
async def test_learning_loop_record_prediction():
    """record_prediction() inserts a row and returns a UUID."""
    from companion.learning import LearningLoop

    pool, conn = _make_pool()
    loop = LearningLoop(pool)

    pred_id = await loop.record_prediction(
        user_id="henning",
        session_id="s1",
        context="battery at 30%",
        prediction="charge to 80%",
        confidence=0.88,
        category="energy",
    )

    assert isinstance(pred_id, str) and len(pred_id) == 36
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_learning_loop_record_feedback_correct():
    """record_feedback(correct=True) updates predictions and inserts feedback row."""
    from companion.learning import LearningLoop

    pool, conn = _make_pool()
    loop = LearningLoop(pool)

    feedback_id = await loop.record_feedback(
        prediction_id="pred-1",
        correct=True,
    )

    assert isinstance(feedback_id, str) and len(feedback_id) == 36
    assert conn.execute.call_count == 2  # INSERT feedback + UPDATE prediction


@pytest.mark.asyncio
async def test_learning_loop_record_feedback_with_correction_updates_pref_graph():
    """record_feedback(correct=False, correction=...) propagates to PreferenceGraph."""
    from companion.learning import LearningLoop
    from companion.preference_graph import PreferenceGraph

    pool, conn = _make_pool(
        fetchrow_result={
            "user_id": "henning",
            "context": "battery low",
            "category": "energy",
        }
    )

    mock_graph = AsyncMock()
    mock_graph.upsert = AsyncMock(return_value=str(uuid4()))
    loop = LearningLoop(pool, preference_graph=mock_graph)

    await loop.record_feedback(
        prediction_id="pred-1",
        correct=False,
        correction="charge to 100% before a long trip",
    )

    mock_graph.upsert.assert_called_once()
    call_kwargs = mock_graph.upsert.call_args[1]
    assert call_kwargs["confidence"] == 1.0
    assert "long trip" in call_kwargs["value"]


@pytest.mark.asyncio
async def test_learning_loop_accuracy_report_all_correct():
    """get_accuracy_report() returns 100% when all predictions were correct."""
    from companion.learning import LearningLoop

    rows = [
        _make_prediction_row(feedback_correct=True),
        _make_prediction_row(feedback_correct=True),
        _make_prediction_row(feedback_correct=True),
    ]
    pool, _ = _make_pool(fetch_results=rows)
    loop = LearningLoop(pool)

    report = await loop.get_accuracy_report(user_id="henning", days=30)

    assert report.total == 3
    assert report.correct == 3
    assert report.incorrect == 0
    assert report.pending == 0
    assert report.accuracy_pct == 100.0


@pytest.mark.asyncio
async def test_learning_loop_accuracy_report_mixed():
    """get_accuracy_report() correctly counts correct/incorrect/pending."""
    from companion.learning import LearningLoop

    rows = [
        _make_prediction_row(feedback_correct=True, category="energy"),
        _make_prediction_row(feedback_correct=False, category="energy"),
        _make_prediction_row(feedback_correct=None, category="work"),   # pending
    ]
    pool, _ = _make_pool(fetch_results=rows)
    loop = LearningLoop(pool)

    report = await loop.get_accuracy_report(user_id="henning", days=30)

    assert report.total == 3
    assert report.correct == 1
    assert report.incorrect == 1
    assert report.pending == 1
    assert report.accuracy_pct == 50.0
    assert "energy" in report.by_category


@pytest.mark.asyncio
async def test_learning_loop_accuracy_report_no_predictions():
    """get_accuracy_report() handles zero predictions gracefully."""
    from companion.learning import LearningLoop

    pool, _ = _make_pool(fetch_results=[])
    loop = LearningLoop(pool)

    report = await loop.get_accuracy_report(user_id="henning", days=30)

    assert report.total == 0
    assert report.accuracy_pct == 0.0


@pytest.mark.asyncio
async def test_learning_loop_get_pending_predictions():
    """get_pending_predictions() returns rows without feedback_correct set."""
    from companion.learning import LearningLoop

    rows = [_make_prediction_row(feedback_correct=None) for _ in range(2)]
    pool, _ = _make_pool(fetch_results=rows)
    loop = LearningLoop(pool)

    preds = await loop.get_pending_predictions(user_id="henning", limit=5)
    assert len(preds) == 2
    assert all("prediction_id" in p for p in preds)


# ===========================================================================
# Phase 4 — DelegationEngine
# ===========================================================================


def test_delegation_engine_score_below_threshold():
    """score() returns should_delegate=False when confidence < threshold."""
    from companion.delegation import DelegationEngine, DelegationPolicy

    engine = DelegationEngine()
    # auto_send is False by default — always requires confirmation
    decision = engine.score(
        action="set EV charge limit to 80%",
        context="energy",
        base_confidence=0.70,
    )

    assert decision.should_delegate is False
    assert decision.requires_confirmation is True
    assert decision.confirmation_message is not None
    assert "80%" in decision.confirmation_message


def test_delegation_engine_score_auto_send_enabled():
    """score() returns should_delegate=True when auto_send=True and confidence >= threshold."""
    from companion.delegation import DelegationEngine, DelegationPolicy

    engine = DelegationEngine()
    engine.set_policy(
        DelegationPolicy(context="work", threshold=0.80, auto_send=True)
    )

    decision = engine.score(
        action="restart the pv-forecast service",
        context="work",
        base_confidence=0.90,
    )

    assert decision.should_delegate is True
    assert decision.requires_confirmation is False
    assert decision.confirmation_message is None


def test_delegation_engine_score_always_confirm_overrides():
    """always_confirm=True blocks delegation even above threshold with auto_send."""
    from companion.delegation import DelegationEngine, DelegationPolicy

    engine = DelegationEngine()
    engine.set_policy(
        DelegationPolicy(
            context="family",
            threshold=0.60,
            auto_send=True,
            always_confirm=True,
        )
    )

    decision = engine.score(
        action="create calendar event",
        context="family",
        base_confidence=0.99,
    )

    assert decision.should_delegate is False
    assert decision.requires_confirmation is True


def test_delegation_engine_supporting_evidence_boosts_confidence():
    """Supporting evidence increases effective confidence by 2 pp each (capped +10pp)."""
    from companion.delegation import DelegationEngine, DelegationPolicy

    engine = DelegationEngine()
    engine.set_policy(
        DelegationPolicy(context="energy", threshold=0.85, auto_send=True)
    )

    decision_no_evidence = engine.score(
        action="start EV charge",
        context="energy",
        base_confidence=0.84,
    )
    decision_with_evidence = engine.score(
        action="start EV charge",
        context="energy",
        base_confidence=0.84,
        supporting_evidence=["PV excess 2 kW", "cheap grid rate"],
    )

    assert decision_with_evidence.confidence > decision_no_evidence.confidence
    assert decision_with_evidence.should_delegate is True
    assert decision_no_evidence.should_delegate is False


def test_delegation_engine_contradicting_evidence_lowers_confidence():
    """Contradicting evidence decreases effective confidence by 5 pp each."""
    from companion.delegation import DelegationEngine

    engine = DelegationEngine()
    base = 0.95

    decision_clean = engine.score("charge EV", "energy", base)
    decision_contra = engine.score(
        "charge EV",
        "energy",
        base,
        contradicting_evidence=["car already full", "overnight cheap rate not available"],
    )

    assert decision_contra.confidence < decision_clean.confidence


def test_delegation_engine_calibrate_raises_threshold_on_low_accuracy():
    """calibrate_from_accuracy() raises threshold when accuracy < 70%."""
    from companion.delegation import DelegationEngine

    engine = DelegationEngine()
    original = engine.get_policy("energy").threshold

    engine.calibrate_from_accuracy("energy", accuracy_pct=60.0, sample_size=15)

    assert engine.get_policy("energy").threshold > original


def test_delegation_engine_calibrate_lowers_threshold_on_high_accuracy():
    """calibrate_from_accuracy() lowers threshold when accuracy >= 90%."""
    from companion.delegation import DelegationEngine

    engine = DelegationEngine()
    original = engine.get_policy("work").threshold

    engine.calibrate_from_accuracy("work", accuracy_pct=95.0, sample_size=20)

    assert engine.get_policy("work").threshold < original


def test_delegation_engine_calibrate_ignores_small_sample():
    """calibrate_from_accuracy() does nothing when sample_size < 10."""
    from companion.delegation import DelegationEngine

    engine = DelegationEngine()
    original = engine.get_policy("energy").threshold

    engine.calibrate_from_accuracy("energy", accuracy_pct=55.0, sample_size=5)

    assert engine.get_policy("energy").threshold == original


def test_delegation_decision_to_dict():
    """DelegationDecision.to_dict() returns all expected keys."""
    from companion.delegation import DelegationEngine

    engine = DelegationEngine()
    decision = engine.score("test action", "general", 0.5)
    d = decision.to_dict()

    expected_keys = {
        "should_delegate", "confidence", "threshold", "context",
        "action", "reasoning", "requires_confirmation", "confirmation_message",
    }
    assert expected_keys == set(d.keys())


# ===========================================================================
# HenningGPT Router — endpoint smoke tests
# ===========================================================================


@pytest.mark.asyncio
async def test_henninggpt_router_store_decision():
    """POST /companion/henninggpt/decisions stores and returns decision_id."""
    from companion import henninggpt_router as hr_module
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    mock_mem = AsyncMock()
    mock_mem.store = AsyncMock(return_value="dec-abc")

    hr_module._decision_memory = mock_mem
    hr_module._preference_graph = AsyncMock()
    hr_module._learning_loop = AsyncMock()
    hr_module._delegation_engine = MagicMock()

    app = FastAPI()
    app.include_router(hr_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/henninggpt/decisions",
            json={
                "user_id": "henning",
                "context": "battery low",
                "decision": "charge now",
                "reasoning": "trip tomorrow",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["decision_id"] == "dec-abc"


@pytest.mark.asyncio
async def test_henninggpt_router_search_decisions():
    """POST /companion/henninggpt/decisions/search returns a list."""
    from companion import henninggpt_router as hr_module
    from companion.decision_memory import DecisionEntry
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    entry = DecisionEntry(
        decision_id="d1",
        user_id="henning",
        context="battery",
        decision="charge to 80%",
        reasoning="trip",
    )
    mock_mem = AsyncMock()
    mock_mem.search = AsyncMock(return_value=[entry])

    hr_module._decision_memory = mock_mem
    hr_module._preference_graph = AsyncMock()
    hr_module._learning_loop = AsyncMock()
    hr_module._delegation_engine = MagicMock()

    app = FastAPI()
    app.include_router(hr_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/henninggpt/decisions/search",
            json={"query": "charge battery EV"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["decisions"][0]["decision_id"] == "d1"


@pytest.mark.asyncio
async def test_henninggpt_router_upsert_preference():
    """POST /companion/henninggpt/preferences returns node_id."""
    from companion import henninggpt_router as hr_module
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    mock_graph = AsyncMock()
    mock_graph.upsert = AsyncMock(return_value="node-123")

    hr_module._decision_memory = AsyncMock()
    hr_module._preference_graph = mock_graph
    hr_module._learning_loop = AsyncMock()
    hr_module._delegation_engine = MagicMock()

    app = FastAPI()
    app.include_router(hr_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/henninggpt/preferences",
            json={
                "user_id": "henning",
                "key": "ev_charge_limit",
                "value": "80%",
                "context": "energy",
                "why": "battery health",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["node_id"] == "node-123"


@pytest.mark.asyncio
async def test_henninggpt_router_delegate_returns_decision():
    """POST /companion/henninggpt/delegate returns a delegation decision dict."""
    from companion import henninggpt_router as hr_module
    from companion.delegation import DelegationEngine
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    hr_module._decision_memory = AsyncMock()
    hr_module._preference_graph = AsyncMock()
    hr_module._learning_loop = AsyncMock()
    hr_module._delegation_engine = DelegationEngine()

    app = FastAPI()
    app.include_router(hr_module.router)

    with TestClient(app) as client:
        resp = client.post(
            "/companion/henninggpt/delegate",
            json={
                "action": "charge EV to 80%",
                "context": "energy",
                "base_confidence": 0.9,
                "supporting_evidence": ["PV surplus available"],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "should_delegate" in body
    assert "confidence" in body
    assert "threshold" in body


@pytest.mark.asyncio
async def test_henninggpt_router_accuracy_report():
    """GET /companion/henninggpt/accuracy returns accuracy dict."""
    from companion import henninggpt_router as hr_module
    from companion.learning import AccuracyReport
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    report = AccuracyReport(
        total=10,
        correct=8,
        incorrect=2,
        pending=0,
        accuracy_pct=80.0,
        by_category={"energy": {"total": 10, "correct": 8, "incorrect": 2}},
    )

    mock_loop = AsyncMock()
    mock_loop.get_accuracy_report = AsyncMock(return_value=report)

    hr_module._decision_memory = AsyncMock()
    hr_module._preference_graph = AsyncMock()
    hr_module._learning_loop = mock_loop
    hr_module._delegation_engine = MagicMock()

    app = FastAPI()
    app.include_router(hr_module.router)

    with TestClient(app) as client:
        resp = client.get(
            "/companion/henninggpt/accuracy",
            params={"user_id": "henning", "days": 30},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accuracy_pct"] == 80.0
    assert body["correct"] == 8
