"""FastAPI router for HenningGPT Personal AI Model endpoints.

Exposes the four-phase HenningGPT feature set:
  Phase 1 — Decision memory RAG  (/decisions/*)
  Phase 2 — Preference graph     (/preferences/*)
  Phase 3 — Active learning      (/predictions/* + /accuracy)
  Phase 4 — Delegation mode      (/delegate)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from companion.decision_memory import DecisionMemory
from companion.preference_graph import PreferenceGraph
from companion.learning import LearningLoop
from companion.delegation import DelegationEngine, DelegationPolicy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companion/henninggpt", tags=["henninggpt"])

# Module-level singletons — populated by init_henninggpt_router()
_decision_memory: Optional[DecisionMemory] = None
_preference_graph: Optional[PreferenceGraph] = None
_learning_loop: Optional[LearningLoop] = None
_delegation_engine: Optional[DelegationEngine] = None


def init_henninggpt_router(
    decision_memory: DecisionMemory,
    preference_graph: PreferenceGraph,
    learning_loop: LearningLoop,
    delegation_engine: Optional[DelegationEngine] = None,
) -> None:
    """Inject dependencies. Call from orchestrator lifespan before serving."""
    global _decision_memory, _preference_graph, _learning_loop, _delegation_engine
    _decision_memory = decision_memory
    _preference_graph = preference_graph
    _learning_loop = learning_loop
    _delegation_engine = delegation_engine or DelegationEngine()
    logger.info("henninggpt_router_initialized")


def _require_decision_memory() -> DecisionMemory:
    if _decision_memory is None:
        raise HTTPException(503, detail="HenningGPT decision memory not initialised")
    return _decision_memory


def _require_preference_graph() -> PreferenceGraph:
    if _preference_graph is None:
        raise HTTPException(503, detail="HenningGPT preference graph not initialised")
    return _preference_graph


def _require_learning_loop() -> LearningLoop:
    if _learning_loop is None:
        raise HTTPException(503, detail="HenningGPT learning loop not initialised")
    return _learning_loop


def _require_delegation_engine() -> DelegationEngine:
    if _delegation_engine is None:
        raise HTTPException(503, detail="HenningGPT delegation engine not initialised")
    return _delegation_engine


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class StoreDecisionRequest(BaseModel):
    user_id: str
    context: str
    decision: str
    reasoning: str
    outcome: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class SearchDecisionsRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    limit: int = Field(5, ge=1, le=20)


class UpsertPreferenceRequest(BaseModel):
    user_id: str
    key: str
    value: str
    context: str = "general"
    why: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class ConfirmPreferenceRequest(BaseModel):
    user_id: str
    key: str
    context: str = "general"


class RecordPredictionRequest(BaseModel):
    user_id: str
    session_id: str
    context: str
    prediction: str
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    category: str = "general"


class RecordFeedbackRequest(BaseModel):
    correct: bool
    correction: Optional[str] = None


class DelegateRequest(BaseModel):
    action: str
    context: str = "general"
    base_confidence: float = Field(0.7, ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class UpdatePolicyRequest(BaseModel):
    context: str
    threshold: float = Field(0.85, ge=0.50, le=0.99)
    auto_send: bool = False
    always_confirm: bool = False


# ---------------------------------------------------------------------------
# Phase 1 — Decision memory RAG
# ---------------------------------------------------------------------------


@router.post("/decisions")
async def store_decision(body: StoreDecisionRequest) -> dict:
    """Store a new decision in the RAG memory."""
    mem = _require_decision_memory()
    decision_id = await mem.store(
        user_id=body.user_id,
        context=body.context,
        decision=body.decision,
        reasoning=body.reasoning,
        outcome=body.outcome,
        tags=body.tags,
        confidence=body.confidence,
    )
    return {"decision_id": decision_id, "stored": True}


@router.post("/decisions/search")
async def search_decisions(body: SearchDecisionsRequest) -> dict:
    """RAG keyword search over past decisions."""
    mem = _require_decision_memory()
    entries = await mem.search(
        query=body.query,
        user_id=body.user_id,
        limit=body.limit,
    )
    return {"decisions": [e.to_dict() for e in entries], "count": len(entries)}


@router.get("/decisions/recent")
async def get_recent_decisions(user_id: str, limit: int = 10) -> dict:
    """Return the most recent decisions for a user."""
    mem = _require_decision_memory()
    entries = await mem.get_recent(user_id=user_id, limit=limit)
    return {"decisions": [e.to_dict() for e in entries], "count": len(entries)}


@router.patch("/decisions/{decision_id}/outcome")
async def update_decision_outcome(decision_id: str, outcome: str) -> dict:
    """Record the outcome of a past decision."""
    mem = _require_decision_memory()
    await mem.update_outcome(decision_id=decision_id, outcome=outcome)
    return {"decision_id": decision_id, "outcome": outcome, "updated": True}


# ---------------------------------------------------------------------------
# Phase 2 — Preference graph with WHY edges
# ---------------------------------------------------------------------------


@router.post("/preferences")
async def upsert_preference(body: UpsertPreferenceRequest) -> dict:
    """Insert or update a preference node with WHY reasoning."""
    graph = _require_preference_graph()
    node_id = await graph.upsert(
        user_id=body.user_id,
        key=body.key,
        value=body.value,
        context=body.context,
        why=body.why,
        evidence=body.evidence,
        confidence=body.confidence,
    )
    return {"node_id": node_id, "key": body.key, "context": body.context}


@router.get("/preferences")
async def get_preferences(
    user_id: str,
    context: Optional[str] = None,
) -> dict:
    """Query the preference graph for a user, optionally filtered by context."""
    graph = _require_preference_graph()
    nodes = await graph.query(user_id=user_id, context=context)
    return {"preferences": [n.to_dict() for n in nodes], "count": len(nodes)}


@router.post("/preferences/confirm")
async def confirm_preference(body: ConfirmPreferenceRequest) -> dict:
    """Mark a preference as user-confirmed (boosts confidence by 0.1)."""
    graph = _require_preference_graph()
    await graph.confirm(user_id=body.user_id, key=body.key, context=body.context)
    return {"confirmed": True, "key": body.key, "context": body.context}


@router.get("/preferences/persona-context")
async def get_persona_context(user_id: str, message: str) -> dict:
    """Detect the best context domain for a message (multi-context persona selection)."""
    graph = _require_preference_graph()
    context = await graph.select_persona_context(user_id=user_id, message=message)
    return {"context": context, "user_id": user_id}


# ---------------------------------------------------------------------------
# Phase 3 — Active learning loop
# ---------------------------------------------------------------------------


@router.post("/predictions")
async def record_prediction(body: RecordPredictionRequest) -> dict:
    """Record a new AI prediction for later feedback."""
    loop = _require_learning_loop()
    prediction_id = await loop.record_prediction(
        user_id=body.user_id,
        session_id=body.session_id,
        context=body.context,
        prediction=body.prediction,
        confidence=body.confidence,
        category=body.category,
    )
    return {"prediction_id": prediction_id, "recorded": True}


@router.post("/predictions/{prediction_id}/feedback")
async def record_feedback(
    prediction_id: str,
    body: RecordFeedbackRequest,
) -> dict:
    """Record user feedback (correct/incorrect) on a prediction."""
    loop = _require_learning_loop()
    feedback_id = await loop.record_feedback(
        prediction_id=prediction_id,
        correct=body.correct,
        correction=body.correction,
    )
    return {"feedback_id": feedback_id, "prediction_id": prediction_id}


@router.get("/predictions/pending")
async def get_pending_predictions(user_id: str, limit: int = 10) -> dict:
    """Return predictions awaiting feedback."""
    loop = _require_learning_loop()
    preds = await loop.get_pending_predictions(user_id=user_id, limit=limit)
    return {"predictions": preds, "count": len(preds)}


@router.get("/accuracy")
async def get_accuracy_report(user_id: str, days: int = 30) -> dict:
    """Return accuracy report for predictions over the last N days."""
    loop = _require_learning_loop()
    report = await loop.get_accuracy_report(user_id=user_id, days=days)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Phase 4 — Delegation mode
# ---------------------------------------------------------------------------


@router.post("/delegate")
async def score_delegation(body: DelegateRequest) -> dict:
    """Score an action for autonomous delegation.

    Returns should_delegate=True when confidence ≥ threshold and auto_send is enabled,
    otherwise proposes the action with a confirmation message.
    """
    engine = _require_delegation_engine()
    decision = engine.score(
        action=body.action,
        context=body.context,
        base_confidence=body.base_confidence,
        supporting_evidence=body.supporting_evidence,
        contradicting_evidence=body.contradicting_evidence,
    )
    return decision.to_dict()


@router.put("/delegate/policy")
async def update_delegation_policy(body: UpdatePolicyRequest) -> dict:
    """Update delegation policy for a context (threshold, auto_send, always_confirm)."""
    engine = _require_delegation_engine()
    policy = DelegationPolicy(
        context=body.context,
        threshold=body.threshold,
        auto_send=body.auto_send,
        always_confirm=body.always_confirm,
    )
    engine.set_policy(policy)
    return {"policy": policy.__dict__, "updated": True}


@router.get("/delegate/policy/{context}")
async def get_delegation_policy(context: str) -> dict:
    """Return the delegation policy for a context."""
    engine = _require_delegation_engine()
    policy = engine.get_policy(context)
    return policy.__dict__
