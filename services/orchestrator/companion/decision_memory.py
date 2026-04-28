"""Decision memory RAG for HenningGPT — Phase 1.

Stores and retrieves past decisions with context, reasoning, and outcomes.
Uses keyword-overlap scoring for retrieval (no heavy embedding deps).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)


class DecisionEntry:
    """A single stored decision with context and reasoning."""

    def __init__(
        self,
        decision_id: str,
        user_id: str,
        context: str,
        decision: str,
        reasoning: str,
        outcome: Optional[str] = None,
        tags: Optional[list[str]] = None,
        confidence: float = 0.7,
        created_at: Optional[str] = None,
    ) -> None:
        self.decision_id = decision_id
        self.user_id = user_id
        self.context = context
        self.decision = decision
        self.reasoning = reasoning
        self.outcome = outcome
        self.tags = tags or []
        self.confidence = confidence
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "user_id": self.user_id,
            "context": self.context,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "outcome": self.outcome,
            "tags": self.tags,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }

    def to_search_text(self) -> str:
        """Concatenated text for keyword scoring."""
        parts = [self.context, self.decision, self.reasoning]
        if self.outcome:
            parts.append(self.outcome)
        parts.extend(self.tags)
        return " ".join(parts).lower()

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DecisionEntry":
        tags_raw = row.get("tags")
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = []
        else:
            tags = tags_raw or []

        return cls(
            decision_id=str(row["id"]),
            user_id=row["user_id"],
            context=row["context"],
            decision=row["decision"],
            reasoning=row.get("reasoning", ""),
            outcome=row.get("outcome"),
            tags=tags,
            confidence=float(row.get("confidence", 0.7)),
            created_at=str(row.get("created_at", "")),
        )


class DecisionMemory:
    """RAG-backed store of Henning's past decisions.

    Stores decisions in Postgres, retrieves by keyword similarity scoring.
    Keyword overlap is cheap, interpretable, and avoids embedding dependencies.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def store(
        self,
        user_id: str,
        context: str,
        decision: str,
        reasoning: str,
        outcome: Optional[str] = None,
        tags: Optional[list[str]] = None,
        confidence: float = 0.7,
    ) -> str:
        """Store a new decision. Returns decision_id."""
        decision_id = str(uuid4())
        now = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO companion.decisions
                    (id, user_id, context, decision, reasoning, outcome, tags, confidence, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                decision_id,
                user_id,
                context,
                decision,
                reasoning,
                outcome,
                json.dumps(tags or []),
                confidence,
                now,
            )
        logger.info("decision_stored", decision_id=decision_id, user_id=user_id)
        return decision_id

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[DecisionEntry]:
        """Keyword-based RAG search over decisions.

        Scores by term overlap between query tokens and decision text.
        Returns top-k sorted by descending overlap score.
        """
        async with self.pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, context, decision, reasoning, outcome,
                           tags, confidence, created_at
                    FROM companion.decisions
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, context, decision, reasoning, outcome,
                           tags, confidence, created_at
                    FROM companion.decisions
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )

        if not rows:
            return []

        query_terms = set(query.lower().split())
        scored: list[tuple[int, DecisionEntry]] = []
        for row in rows:
            entry = DecisionEntry.from_row(dict(row))
            text_terms = set(entry.to_search_text().split())
            overlap = len(query_terms & text_terms)
            if overlap > 0:
                scored.append((overlap, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def update_outcome(self, decision_id: str, outcome: str) -> None:
        """Record the outcome of a past decision."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE companion.decisions SET outcome = $1 WHERE id = $2",
                outcome,
                decision_id,
            )

    async def get_recent(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[DecisionEntry]:
        """Get most recent decisions for a user."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, context, decision, reasoning, outcome,
                       tags, confidence, created_at
                FROM companion.decisions
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [DecisionEntry.from_row(dict(r)) for r in rows]

    async def to_rag_block(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 3,
    ) -> str:
        """Format top matching decisions as a system-prompt context block."""
        entries = await self.search(query, user_id=user_id, limit=limit)
        if not entries:
            return ""

        lines = ["### Relevant Past Decisions"]
        for e in entries:
            lines.append(f"- **{e.decision}** (confidence {e.confidence:.0%})")
            lines.append(f"  Context: {e.context}")
            if e.reasoning:
                lines.append(f"  Why: {e.reasoning}")
            if e.outcome:
                lines.append(f"  Outcome: {e.outcome}")
        return "\n".join(lines)
