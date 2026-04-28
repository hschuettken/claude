"""Active learning loop + accuracy tracking for HenningGPT — Phase 3.

Records predictions the AI makes about Henning's preferences/decisions,
collects explicit feedback (correct / incorrect + correction text), and
surfaces an accuracy report that can be used to tune delegation thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class AccuracyReport:
    """Summary of prediction accuracy over a time window."""

    total: int
    correct: int
    incorrect: int
    pending: int
    accuracy_pct: float
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "pending": self.pending,
            "accuracy_pct": round(self.accuracy_pct, 1),
            "by_category": self.by_category,
        }


class LearningLoop:
    """Active learning loop for HenningGPT.

    Lifecycle:
    1. LLM makes a prediction → record_prediction()
    2. Henning gives feedback → record_feedback()
    3. Accuracy is computed per category → get_accuracy_report()
    4. Corrections are fed back to the PreferenceGraph (if provided)

    Designed so the delegation engine can read accuracy-per-category
    and auto-lower/raise thresholds over time.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        preference_graph: Optional[Any] = None,
    ) -> None:
        self.pool = pool
        self.preference_graph = preference_graph

    async def record_prediction(
        self,
        user_id: str,
        session_id: str,
        context: str,
        prediction: str,
        confidence: float,
        category: str = "general",
    ) -> str:
        """Store a new AI prediction. Returns prediction_id."""
        prediction_id = str(uuid4())
        now = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO companion.predictions
                    (id, user_id, session_id, context, prediction,
                     confidence, category, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                prediction_id,
                user_id,
                session_id,
                context,
                prediction,
                confidence,
                category,
                now,
            )

        logger.info(
            "prediction_recorded",
            prediction_id=prediction_id,
            category=category,
            confidence=confidence,
        )
        return prediction_id

    async def record_feedback(
        self,
        prediction_id: str,
        correct: bool,
        correction: Optional[str] = None,
    ) -> str:
        """Record user feedback on a prediction. Returns feedback_id.

        If a correction is provided (and the prediction was wrong),
        the correction is propagated to the PreferenceGraph.
        """
        feedback_id = str(uuid4())
        now = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO companion.prediction_feedback
                    (id, prediction_id, correct, correction, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                feedback_id,
                prediction_id,
                correct,
                correction,
                now,
            )
            await conn.execute(
                """
                UPDATE companion.predictions
                SET feedback_correct = $1, feedback_at = $2
                WHERE id = $3
                """,
                correct,
                now,
                prediction_id,
            )

        logger.info(
            "feedback_recorded",
            prediction_id=prediction_id,
            correct=correct,
        )

        # Propagate correction to PreferenceGraph when available
        if correction and not correct and self.preference_graph is not None:
            try:
                async with self.pool.acquire() as conn:
                    pred_row = await conn.fetchrow(
                        """
                        SELECT user_id, context, category
                        FROM companion.predictions WHERE id = $1
                        """,
                        prediction_id,
                    )
                if pred_row:
                    await self.preference_graph.upsert(
                        user_id=pred_row["user_id"],
                        key=f"correction_{pred_row['category']}",
                        value=correction,
                        context=pred_row["category"] or "general",
                        why="User corrected a wrong prediction",
                        confidence=1.0,
                    )
            except Exception as exc:
                logger.warning(
                    "preference_update_from_feedback_failed",
                    error=str(exc),
                )

        return feedback_id

    async def get_accuracy_report(
        self,
        user_id: str,
        days: int = 30,
    ) -> AccuracyReport:
        """Calculate accuracy stats for the past N days."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT category, feedback_correct
                FROM companion.predictions
                WHERE user_id = $1
                  AND created_at >= NOW() - ($2 * INTERVAL '1 day')
                """,
                user_id,
                days,
            )

        total = len(rows)
        correct = sum(1 for r in rows if r["feedback_correct"] is True)
        incorrect = sum(1 for r in rows if r["feedback_correct"] is False)
        pending = total - correct - incorrect

        by_category: dict[str, dict[str, int]] = {}
        for row in rows:
            cat = row["category"] or "general"
            if cat not in by_category:
                by_category[cat] = {"total": 0, "correct": 0, "incorrect": 0}
            by_category[cat]["total"] += 1
            if row["feedback_correct"] is True:
                by_category[cat]["correct"] += 1
            elif row["feedback_correct"] is False:
                by_category[cat]["incorrect"] += 1

        resolved = correct + incorrect
        accuracy_pct = (correct / resolved * 100.0) if resolved > 0 else 0.0

        return AccuracyReport(
            total=total,
            correct=correct,
            incorrect=incorrect,
            pending=pending,
            accuracy_pct=accuracy_pct,
            by_category=by_category,
        )

    async def get_pending_predictions(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent predictions that have not received feedback yet."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, context, prediction, confidence, category, created_at
                FROM companion.predictions
                WHERE user_id = $1
                  AND feedback_correct IS NULL
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [
            {
                "prediction_id": str(r["id"]),
                "context": r["context"],
                "prediction": r["prediction"],
                "confidence": float(r["confidence"]),
                "category": r["category"],
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]
