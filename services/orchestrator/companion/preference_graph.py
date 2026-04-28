"""Preference graph with WHY edges for HenningGPT — Phase 2.

Each node is a (user_id, key, context) preference.
WHY edges store the reason + evidence backing the preference.
Multi-context persona selection reads this graph to tailor responses.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)

# Valid context domains for persona selection
CONTEXTS = (
    "energy",   # EV charging, PV, heating
    "family",   # Scheduling, activities, people
    "work",     # Dev tasks, focus sessions
    "health",   # Training, nutrition, sleep
    "general",  # Catch-all
)


class PreferenceNode:
    """A single preference with WHY context edge."""

    def __init__(
        self,
        node_id: str,
        user_id: str,
        key: str,
        value: str,
        context: str = "general",
        why: str = "",
        evidence: Optional[list[str]] = None,
        confidence: float = 0.7,
        times_confirmed: int = 0,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        self.node_id = node_id
        self.user_id = user_id
        self.key = key
        self.value = value
        self.context = context
        self.why = why
        self.evidence = evidence or []
        self.confidence = confidence
        self.times_confirmed = times_confirmed
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "user_id": self.user_id,
            "key": self.key,
            "value": self.value,
            "context": self.context,
            "why": self.why,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "times_confirmed": self.times_confirmed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "PreferenceNode":
        evidence_raw = row.get("evidence")
        if isinstance(evidence_raw, str):
            try:
                evidence = json.loads(evidence_raw)
            except (json.JSONDecodeError, TypeError):
                evidence = []
        else:
            evidence = evidence_raw or []

        return cls(
            node_id=str(row["id"]),
            user_id=row["user_id"],
            key=row["key"],
            value=row["value"],
            context=row.get("context", "general"),
            why=row.get("why", ""),
            evidence=evidence,
            confidence=float(row.get("confidence", 0.7)),
            times_confirmed=int(row.get("times_confirmed", 0)),
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
        )


class PreferenceGraph:
    """Graph of Henning's preferences with WHY edges.

    Each node is a (key, value) preference anchored to a context.
    WHY edges express the reason behind the preference, enabling
    the LLM to reason about *why* Henning prefers something rather
    than just knowing *what* he prefers.

    Multi-context persona selection: call to_prompt_block(context=...) to
    inject context-specific preferences into the system prompt.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def upsert(
        self,
        user_id: str,
        key: str,
        value: str,
        context: str = "general",
        why: str = "",
        evidence: Optional[list[str]] = None,
        confidence: float = 0.7,
    ) -> str:
        """Insert or update a preference node. Returns node_id.

        If (user_id, key, context) already exists, updates value/why/confidence.
        """
        now = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id FROM companion.preference_graph
                WHERE user_id = $1 AND key = $2 AND context = $3
                """,
                user_id,
                key,
                context,
            )

            if existing:
                node_id = str(existing["id"])
                await conn.execute(
                    """
                    UPDATE companion.preference_graph
                    SET value = $1, why = $2, evidence = $3, confidence = $4, updated_at = $5
                    WHERE id = $6
                    """,
                    value,
                    why,
                    json.dumps(evidence or []),
                    confidence,
                    now,
                    node_id,
                )
                logger.info("preference_updated", node_id=node_id, key=key)
            else:
                node_id = str(uuid4())
                await conn.execute(
                    """
                    INSERT INTO companion.preference_graph
                        (id, user_id, key, value, context, why, evidence,
                         confidence, times_confirmed, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, $9, $10)
                    """,
                    node_id,
                    user_id,
                    key,
                    value,
                    context,
                    why,
                    json.dumps(evidence or []),
                    confidence,
                    now,
                    now,
                )
                logger.info("preference_created", node_id=node_id, key=key)

        return node_id

    async def confirm(
        self,
        user_id: str,
        key: str,
        context: str = "general",
    ) -> None:
        """Increment times_confirmed and boost confidence (max 1.0)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE companion.preference_graph
                SET
                    times_confirmed = times_confirmed + 1,
                    confidence = LEAST(confidence + 0.1, 1.0),
                    updated_at = $1
                WHERE user_id = $2 AND key = $3 AND context = $4
                """,
                datetime.now(timezone.utc),
                user_id,
                key,
                context,
            )

    async def query(
        self,
        user_id: str,
        context: Optional[str] = None,
        keys: Optional[list[str]] = None,
    ) -> list[PreferenceNode]:
        """Query preferences by user + optional context + optional key filter."""
        conditions = ["user_id = $1"]
        params: list[Any] = [user_id]

        if context:
            params.append(context)
            conditions.append(f"context = ${len(params)}")

        where = " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, user_id, key, value, context, why, evidence,
                       confidence, times_confirmed, created_at, updated_at
                FROM companion.preference_graph
                WHERE {where}
                ORDER BY confidence DESC, times_confirmed DESC
                """,
                *params,
            )

        nodes = [PreferenceNode.from_row(dict(r)) for r in rows]

        if keys:
            keys_lower = {k.lower() for k in keys}
            nodes = [n for n in nodes if n.key.lower() in keys_lower]

        return nodes

    async def select_persona_context(
        self,
        user_id: str,
        message: str,
    ) -> str:
        """Select the most relevant context domain for a message.

        Matches message tokens against known preference keys in each context,
        returning the domain with the most matching preferences.
        Falls back to "general" when no clear winner.
        """
        tokens = set(message.lower().split())

        context_keywords: dict[str, set[str]] = {
            "energy": {"solar", "pv", "ev", "charge", "battery", "power", "watt",
                       "kWh", "kwh", "grid", "heating", "oil", "energy"},
            "family": {"family", "nicole", "kids", "children", "calendar", "event",
                       "appointment", "school", "weekend", "vacation", "trip"},
            "work": {"code", "deploy", "build", "test", "branch", "pr", "bug",
                     "feature", "service", "docker", "server", "infra"},
            "health": {"training", "run", "sleep", "nutrition", "gym", "bike",
                       "weight", "calories", "health", "sauna", "workout"},
        }

        best_ctx = "general"
        best_score = 0
        for ctx, keywords in context_keywords.items():
            score = len(tokens & keywords)
            if score > best_score:
                best_score = score
                best_ctx = ctx

        return best_ctx

    async def to_prompt_block(
        self,
        user_id: str,
        context: Optional[str] = None,
        max_nodes: int = 20,
    ) -> str:
        """Format preferences as a system prompt block for LLM injection."""
        nodes = await self.query(user_id, context=context)
        if not nodes:
            return ""

        lines = ["### Henning's Preferences"]
        for node in nodes[:max_nodes]:
            why_part = f" (why: {node.why})" if node.why else ""
            conf_part = f" [{node.confidence:.0%}]"
            lines.append(
                f"- **{node.key}** [{node.context}]: {node.value}{why_part}{conf_part}"
            )

        return "\n".join(lines)
