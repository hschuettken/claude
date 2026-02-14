"""Structured knowledge store and memory document manager.

Two complementary persistence layers for learned knowledge:

1. **KnowledgeStore** — Typed, structured facts that services can query
   programmatically (destinations, person patterns, preferences, corrections).
   Published via MQTT so downstream services (ev-forecast, smart-ev-charging)
   can consume learned knowledge.

2. **MemoryDocument** — A living ``memory.md`` file the LLM reads and
   maintains.  Think of it as the orchestrator's personal notebook — human-
   readable, nuanced, captures context that doesn't fit into typed facts.
   Injected into the system prompt so the LLM has continuity across sessions.

Data files:
    /app/data/memory/knowledge.json    — structured facts
    /app/data/memory/memory.md         — LLM-maintained notes
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from shared.log import get_logger

logger = get_logger("knowledge")

DATA_DIR = Path("/app/data/memory")
KNOWLEDGE_FILE = DATA_DIR / "knowledge.json"
MEMORY_MD_FILE = DATA_DIR / "memory.md"

# Valid fact types
FACT_TYPES = {"destination", "person_pattern", "preference", "correction", "general"}

MEMORY_MD_SEED = """\
# Memory

*This document is maintained by the orchestrator AI.  Update it whenever you \
learn something worth remembering.  Keep it concise — this is injected into \
every conversation.*

## Household


## Destinations & Distances


## Preferences & Habits


## Patterns & Rules


## Important Notes

"""


# ------------------------------------------------------------------
# Structured knowledge store
# ------------------------------------------------------------------


class KnowledgeStore:
    """Persistent store for typed, structured facts.

    Each fact has:
        id          — unique identifier
        type        — one of FACT_TYPES (destination, person_pattern, …)
        key         — normalised lookup key (lowercase, stripped)
        data        — dict with type-specific fields
        confidence  — 1.0 = user confirmed, 0.7 = LLM inferred
        source      — where the fact came from (trip_clarification, conversation, explicit)
        timestamp   — when it was stored
        times_used  — how often the fact has been looked up
    """

    def __init__(self, mqtt: Any = None) -> None:
        self._mqtt = mqtt
        self._facts: list[dict[str, Any]] = []
        self._load()

    # ---- Public API --------------------------------------------------

    def store(
        self,
        fact_type: str,
        key: str,
        data: dict[str, Any],
        confidence: float = 1.0,
        source: str = "explicit",
    ) -> str:
        """Store a structured fact.  Returns the fact ID."""
        if fact_type not in FACT_TYPES:
            raise ValueError(f"Invalid fact type '{fact_type}', must be one of {FACT_TYPES}")

        norm_key = key.lower().strip()

        # Check for existing fact with same type+key — update instead of duplicate
        existing = self._find_exact(fact_type, norm_key)
        if existing is not None:
            existing["data"].update(data)
            existing["confidence"] = max(existing["confidence"], confidence)
            existing["source"] = source
            existing["timestamp"] = time.time()
            self._save()
            self._publish_update("updated", existing)
            logger.info("knowledge_updated", type=fact_type, key=norm_key)
            return existing["id"]

        fact_id = uuid.uuid4().hex[:12]
        fact: dict[str, Any] = {
            "id": fact_id,
            "type": fact_type,
            "key": norm_key,
            "data": data,
            "confidence": confidence,
            "source": source,
            "timestamp": time.time(),
            "times_used": 0,
        }
        self._facts.append(fact)
        self._save()
        self._publish_update("stored", fact)
        logger.info("knowledge_stored", id=fact_id, type=fact_type, key=norm_key)
        return fact_id

    def get(self, fact_type: str, key: str) -> dict[str, Any] | None:
        """Exact-match lookup by type and key."""
        fact = self._find_exact(fact_type, key.lower().strip())
        if fact:
            fact["times_used"] += 1
            self._save()
        return fact

    def search(self, fact_type: str | None = None, query: str = "") -> list[dict[str, Any]]:
        """Fuzzy search across facts.  Matches query against key and data values."""
        query_lower = query.lower().strip()
        results: list[dict[str, Any]] = []

        for fact in self._facts:
            if fact_type and fact["type"] != fact_type:
                continue
            if not query_lower:
                results.append(fact)
                continue
            # Match against key
            if query_lower in fact["key"] or fact["key"] in query_lower:
                results.append(fact)
                continue
            # Match against data values
            for v in fact["data"].values():
                if isinstance(v, str) and query_lower in v.lower():
                    results.append(fact)
                    break

        # Sort by confidence descending, then recency
        results.sort(key=lambda f: (f["confidence"], f["timestamp"]), reverse=True)
        return results

    def get_all(self, fact_type: str | None = None) -> list[dict[str, Any]]:
        """Return all facts, optionally filtered by type."""
        if fact_type:
            return [f for f in self._facts if f["type"] == fact_type]
        return list(self._facts)

    def delete(self, fact_id: str) -> bool:
        """Delete a fact by ID."""
        before = len(self._facts)
        self._facts = [f for f in self._facts if f["id"] != fact_id]
        if len(self._facts) < before:
            self._save()
            return True
        return False

    @property
    def count(self) -> int:
        return len(self._facts)

    # ---- Internal ----------------------------------------------------

    def _find_exact(self, fact_type: str, norm_key: str) -> dict[str, Any] | None:
        for f in self._facts:
            if f["type"] == fact_type and f["key"] == norm_key:
                return f
        return None

    def _publish_update(self, action: str, fact: dict[str, Any]) -> None:
        """Publish knowledge update via MQTT so other services can consume."""
        if not self._mqtt:
            return
        try:
            self._mqtt.publish("homelab/orchestrator/knowledge-update", {
                "action": action,
                "type": fact["type"],
                "key": fact["key"],
                "data": fact["data"],
                "confidence": fact["confidence"],
                "source": fact["source"],
                "timestamp": fact["timestamp"],
            })
        except Exception:
            logger.debug("knowledge_mqtt_publish_failed")

    def _load(self) -> None:
        try:
            raw = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
            self._facts = raw.get("facts", [])
            logger.info("knowledge_loaded", facts=len(self._facts))
        except (FileNotFoundError, json.JSONDecodeError):
            self._facts = []
            logger.info("knowledge_empty")

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = KNOWLEDGE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"facts": self._facts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.rename(KNOWLEDGE_FILE)


# ------------------------------------------------------------------
# Memory document (memory.md)
# ------------------------------------------------------------------


class MemoryDocument:
    """Manages the LLM's living memory.md document.

    The document is:
    - Read on every conversation turn (injected into system prompt)
    - Written by the LLM via a tool when it learns something new
    - Human-readable and editable (plain Markdown on the data volume)
    - Capped at a configurable max size to avoid bloating the context
    """

    def __init__(self, max_size: int = 4000) -> None:
        self._max_size = max_size
        self._ensure_exists()

    def read(self) -> str:
        """Return the current memory document content."""
        try:
            content = MEMORY_MD_FILE.read_text(encoding="utf-8")
            return content[:self._max_size]
        except FileNotFoundError:
            self._ensure_exists()
            return MEMORY_MD_SEED

    def write(self, content: str) -> bool:
        """Replace the memory document content.  Returns True on success."""
        if len(content) > self._max_size:
            logger.warning(
                "memory_doc_truncated",
                original_len=len(content),
                max_size=self._max_size,
            )
            content = content[:self._max_size]

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Keep one backup
        if MEMORY_MD_FILE.exists():
            backup = MEMORY_MD_FILE.with_suffix(".md.bak")
            try:
                backup.write_text(MEMORY_MD_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass

        tmp = MEMORY_MD_FILE.with_suffix(".md.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.rename(MEMORY_MD_FILE)
            logger.info("memory_doc_updated", size=len(content))
            return True
        except OSError:
            logger.exception("memory_doc_write_failed")
            return False

    @property
    def size(self) -> int:
        """Current document size in characters."""
        try:
            return MEMORY_MD_FILE.stat().st_size
        except FileNotFoundError:
            return 0

    def _ensure_exists(self) -> None:
        """Create the memory document with seed content if missing."""
        if not MEMORY_MD_FILE.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            MEMORY_MD_FILE.write_text(MEMORY_MD_SEED, encoding="utf-8")
            logger.info("memory_doc_created")
