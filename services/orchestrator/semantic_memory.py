"""Semantic long-term memory backed by vector embeddings.

Stores conversation snippets, learned facts, and decisions as embedded
vectors for later semantic retrieval.  The orchestrator can recall
relevant past context even after the short-term conversation history
has been trimmed.

**No heavy dependencies** — uses the already-configured LLM provider's
embedding API (Gemini ``text-embedding-004`` by default) and pure-Python
cosine similarity.  Storage is a simple JSON file.

Typical scale: a few thousand entries over months → fits comfortably in
memory and searches in milliseconds.

Features:
- Time-weighted scoring — blends cosine similarity with recency
- LLM-powered summarization — conversations are distilled before storage
- Periodic consolidation — merges related memories to reduce noise
"""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

from shared.log import get_logger

logger = get_logger("semantic-memory")

STORE_FILE = Path("/app/data/memory/semantic_store.json")
MAX_ENTRIES = 5000  # cap to keep file size reasonable (~20 MB)

# Time-weighted scoring parameters
RECENCY_WEIGHT = 0.15  # 0 = pure similarity, 1 = pure recency
RECENCY_HALF_LIFE_DAYS = 30  # after 30 days, recency score = 0.5


# ------------------------------------------------------------------
# Embedding providers
# ------------------------------------------------------------------


class EmbeddingProvider:
    """Get text embeddings from the configured LLM provider."""

    def __init__(self, provider: str, settings: Any) -> None:
        self._provider = provider
        self._settings = settings

    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector for *text*."""
        # Try providers in preference order
        for fn in (self._embed_gemini, self._embed_openai):
            try:
                return await fn(text)
            except Exception:
                continue
        raise RuntimeError("No embedding provider available")

    async def _embed_gemini(self, text: str) -> list[float]:
        s = self._settings
        api_key = s.gemini_api_key
        if not api_key:
            raise RuntimeError("No Gemini API key")

        from google import genai

        client = genai.Client(api_key=api_key)
        result = await client.aio.models.embed_content(
            model="text-embedding-004",
            contents=text,
        )
        return list(result.embeddings[0].values)

    async def _embed_openai(self, text: str) -> list[float]:
        s = self._settings
        api_key = s.openai_api_key
        base_url = None
        model = "text-embedding-3-small"

        if not api_key and self._provider == "ollama":
            api_key = "ollama"
            base_url = f"{s.ollama_url}/v1"
            model = "nomic-embed-text"
        if not api_key:
            raise RuntimeError("No OpenAI API key")

        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        result = await client.embeddings.create(model=model, input=[text])
        return result.data[0].embedding


# ------------------------------------------------------------------
# Vector store
# ------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity — fast enough for <10 k entries."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticMemory:
    """Persistent vector store for long-term orchestrator memory.

    Categories:
        conversation — auto-stored summaries of past exchanges
        fact         — explicitly stored knowledge (via LLM tool)
        decision     — orchestrator decisions and their outcomes
    """

    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder
        self._entries: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store(
        self,
        text: str,
        category: str = "conversation",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Embed and store a text entry.  Returns the entry ID."""
        try:
            embedding = await self._embedder.embed(text[:2000])
        except Exception:
            logger.warning("embedding_failed", text_len=len(text))
            return ""

        entry_id = uuid.uuid4().hex[:12]
        entry: dict[str, Any] = {
            "id": entry_id,
            "text": text[:2000],
            "embedding": embedding,
            "category": category,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self._entries.append(entry)

        # Trim oldest entries if over limit
        if len(self._entries) > MAX_ENTRIES:
            self._entries = self._entries[-MAX_ENTRIES:]

        self._save()
        logger.debug("memory_stored", id=entry_id, category=category, text_len=len(text))
        return entry_id

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search with time-weighted scoring.

        Final score = (1 - w) * similarity + w * recency
        where recency decays exponentially with a configurable half-life.
        """
        if not self._entries:
            return []

        try:
            query_embedding = await self._embedder.embed(query[:2000])
        except Exception:
            logger.warning("search_embedding_failed")
            return []

        candidates = self._entries
        if category:
            candidates = [e for e in candidates if e.get("category") == category]

        now = time.time()
        scored: list[tuple[float, float, dict[str, Any]]] = []
        for entry in candidates:
            sim = _cosine_similarity(query_embedding, entry["embedding"])
            age_days = (now - entry["timestamp"]) / 86400
            recency = math.exp(-0.693 * age_days / RECENCY_HALF_LIFE_DAYS)
            combined = (1 - RECENCY_WEIGHT) * sim + RECENCY_WEIGHT * recency
            scored.append((combined, sim, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for combined, sim, entry in scored[:top_k]:
            results.append({
                "id": entry["id"],
                "text": entry["text"],
                "category": entry["category"],
                "metadata": entry["metadata"],
                "similarity": round(sim, 3),
                "score": round(combined, 3),
                "age_days": round((now - entry["timestamp"]) / 86400, 1),
            })
        return results

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get_entries_for_consolidation(
        self,
        category: str = "conversation",
        min_age_days: float = 1.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return older entries suitable for consolidation."""
        cutoff = time.time() - min_age_days * 86400
        candidates = [
            e for e in self._entries
            if e.get("category") == category
            and e["timestamp"] < cutoff
            and not e.get("metadata", {}).get("consolidated")
        ]
        # Oldest first
        candidates.sort(key=lambda e: e["timestamp"])
        return candidates[:limit]

    async def replace_with_consolidated(
        self,
        old_ids: list[str],
        consolidated_text: str,
        category: str = "conversation",
    ) -> str:
        """Replace multiple entries with a single consolidated entry."""
        if not old_ids:
            return ""

        try:
            embedding = await self._embedder.embed(consolidated_text[:2000])
        except Exception:
            logger.warning("consolidation_embedding_failed")
            return ""

        # Remove old entries
        old_set = set(old_ids)
        self._entries = [e for e in self._entries if e["id"] not in old_set]

        # Add consolidated entry
        entry_id = uuid.uuid4().hex[:12]
        entry: dict[str, Any] = {
            "id": entry_id,
            "text": consolidated_text[:2000],
            "embedding": embedding,
            "category": category,
            "metadata": {"consolidated": True, "merged_count": len(old_ids)},
            "timestamp": time.time(),
        }
        self._entries.append(entry)
        self._save()

        logger.info(
            "memories_consolidated",
            merged=len(old_ids),
            new_id=entry_id,
            total=len(self._entries),
        )
        return entry_id

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            self._entries = data.get("entries", [])
            logger.info("semantic_memory_loaded", entries=len(self._entries))
        except (FileNotFoundError, json.JSONDecodeError):
            self._entries = []
            logger.info("semantic_memory_empty")

    def _save(self) -> None:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"entries": self._entries}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.rename(STORE_FILE)
