"""Semantic long-term memory backed by vector embeddings.

Stores conversation snippets, learned facts, and decisions as embedded
vectors for later semantic retrieval. The orchestrator can recall
relevant past context even after the short-term conversation history
has been trimmed.

Storage is backed by ChromaDB via the shared ChromaClient.

Features:
- Time-weighted scoring — blends vector similarity with recency
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

from shared.chroma_client import ChromaClient, COLLECTION_ORCHESTRATOR_MEMORY
from shared.log import get_logger

logger = get_logger("semantic-memory")

STORE_FILE = Path("/app/data/memory/semantic_store.json")

# Defaults — overridden by OrchestratorSettings when passed to SemanticMemory
DEFAULT_MAX_ENTRIES = 5000
DEFAULT_TEXT_MAX_LEN = 2000
DEFAULT_RECENCY_WEIGHT = 0.15
DEFAULT_RECENCY_HALF_LIFE_DAYS = 30


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
        errors: list[str] = []
        for fn in (self._embed_gemini, self._embed_openai):
            try:
                return await fn(text)
            except Exception as exc:
                errors.append(f"{fn.__name__}: {exc}")
                continue
        logger.warning("all_embedding_providers_failed", errors=errors)
        raise RuntimeError(f"No embedding provider available: {'; '.join(errors)}")

    async def _embed_gemini(self, text: str) -> list[float]:
        s = self._settings
        api_key = s.gemini_api_key
        if not api_key:
            raise RuntimeError("No Gemini API key")

        model = getattr(s, "gemini_embedding_model", "gemini-embedding-001")
        dims = getattr(s, "gemini_embedding_dims", 768)

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        result = await client.aio.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=dims),
        )
        return list(result.embeddings[0].values)

    async def _embed_openai(self, text: str) -> list[float]:
        s = self._settings
        api_key = s.openai_api_key
        base_url = None
        model = getattr(s, "openai_embedding_model", "text-embedding-3-small")

        if not api_key and self._provider == "ollama":
            api_key = "ollama"
            base_url = f"{s.ollama_url}/v1"
            model = getattr(s, "ollama_embedding_model", "nomic-embed-text")
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
# Vector helpers
# ------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity utility."""
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

    def __init__(
        self,
        chroma: ChromaClient,
        embedder: EmbeddingProvider,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        text_max_len: int = DEFAULT_TEXT_MAX_LEN,
        recency_weight: float = DEFAULT_RECENCY_WEIGHT,
        recency_half_life_days: int = DEFAULT_RECENCY_HALF_LIFE_DAYS,
    ) -> None:
        self._chroma = chroma
        self._embedder = embedder
        self._max_entries = max_entries
        self._text_max_len = text_max_len
        self._recency_weight = recency_weight
        self._recency_half_life_days = recency_half_life_days
        self._collection = COLLECTION_ORCHESTRATOR_MEMORY

        self._migrate_legacy_json_if_needed()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store(
        self,
        text: str,
        category: str = "conversation",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Embed and store a text entry. Returns the entry ID."""
        max_len = self._text_max_len
        text_to_store = text[:max_len]
        try:
            embedding = await self._embedder.embed(text_to_store)
        except Exception:
            logger.warning("embedding_failed", text_len=len(text))
            return ""

        entry_id = uuid.uuid4().hex[:12]
        now_ts = time.time()
        meta = {
            "category": category,
            "timestamp": now_ts,
            **(metadata or {}),
        }

        try:
            self._chroma.store(
                collection_name=self._collection,
                doc_id=entry_id,
                text=text_to_store,
                embedding=embedding,
                metadata=meta,
            )
            self._trim_if_over_limit()
        except Exception as exc:
            logger.warning("semantic_store_failed", error=str(exc))
            return ""

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
        try:
            query_embedding = await self._embedder.embed(query[:self._text_max_len])
        except Exception:
            logger.warning("search_embedding_failed")
            return []

        where = {"category": category} if category else None
        fetch_k = max(top_k * 3, top_k)

        try:
            raw = self._chroma.search(
                collection_name=self._collection,
                query_embedding=query_embedding,
                top_k=fetch_k,
                where=where,
            )
        except Exception as exc:
            logger.warning("semantic_search_failed", error=str(exc))
            return []

        if not raw:
            return []

        now = time.time()
        scored: list[tuple[float, float, dict[str, Any], float]] = []
        for item in raw:
            metadata = item.get("metadata") or {}
            timestamp = float(metadata.get("timestamp", now))
            distance = float(item.get("distance", 1.0))
            similarity = 1.0 - distance
            age_days = (now - timestamp) / 86400
            recency = math.exp(-0.693 * age_days / self._recency_half_life_days)
            combined = (1 - self._recency_weight) * similarity + self._recency_weight * recency
            scored.append((combined, similarity, item, age_days))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for combined, sim, item, age_days in scored[:top_k]:
            metadata = dict(item.get("metadata") or {})
            result_category = metadata.get("category", "conversation")
            metadata.pop("category", None)
            results.append(
                {
                    "id": item.get("id", ""),
                    "text": item.get("text", ""),
                    "category": result_category,
                    "metadata": metadata,
                    "similarity": round(sim, 3),
                    "score": round(combined, 3),
                    "age_days": round(age_days, 1),
                }
            )
        return results

    @property
    def entry_count(self) -> int:
        try:
            return self._chroma.count(self._collection)
        except Exception as exc:
            logger.warning("semantic_count_failed", error=str(exc))
            return 0

    def get_entries_for_consolidation(
        self,
        category: str = "conversation",
        min_age_days: float = 1.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return older entries suitable for consolidation."""
        cutoff = time.time() - min_age_days * 86400

        try:
            rows = self._chroma.get(
                collection_name=self._collection,
                where={"category": category},
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.warning("consolidation_fetch_failed", error=str(exc))
            return []

        ids = rows.get("ids", []) or []
        docs = rows.get("documents", []) or []
        metas = rows.get("metadatas", []) or []

        filtered: list[dict[str, Any]] = []
        for i, entry_id in enumerate(ids):
            metadata = dict(metas[i] if i < len(metas) else {})
            timestamp = float(metadata.get("timestamp", 0))
            if timestamp >= cutoff:
                continue
            if metadata.get("consolidated"):
                continue
            filtered.append(
                {
                    "id": entry_id,
                    "text": docs[i] if i < len(docs) else "",
                    "category": metadata.get("category", category),
                    "metadata": metadata,
                    "timestamp": timestamp,
                }
            )

        filtered.sort(key=lambda e: e.get("timestamp", 0.0))
        return filtered[:limit]

    async def replace_with_consolidated(
        self,
        old_ids: list[str],
        consolidated_text: str,
        category: str = "conversation",
    ) -> str:
        """Replace multiple entries with a single consolidated entry."""
        if not old_ids:
            return ""

        max_len = self._text_max_len
        text_to_store = consolidated_text[:max_len]
        try:
            embedding = await self._embedder.embed(text_to_store)
        except Exception:
            logger.warning("consolidation_embedding_failed")
            return ""

        try:
            self._chroma.delete(self._collection, old_ids)
        except Exception as exc:
            logger.warning("consolidation_delete_failed", error=str(exc), ids=len(old_ids))
            return ""

        entry_id = uuid.uuid4().hex[:12]
        metadata = {
            "category": category,
            "timestamp": time.time(),
            "consolidated": True,
            "merged_count": len(old_ids),
        }

        try:
            self._chroma.store(
                collection_name=self._collection,
                doc_id=entry_id,
                text=text_to_store,
                embedding=embedding,
                metadata=metadata,
            )
            self._trim_if_over_limit()
        except Exception as exc:
            logger.warning("consolidation_store_failed", error=str(exc))
            return ""

        logger.info(
            "memories_consolidated",
            merged=len(old_ids),
            new_id=entry_id,
            total=self.entry_count,
        )
        return entry_id

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trim_if_over_limit(self) -> None:
        try:
            total = self._chroma.count(self._collection)
            if total <= self._max_entries:
                return

            overflow = total - self._max_entries
            rows = self._chroma.get(
                collection_name=self._collection,
                include=["metadatas"],
            )
            ids = rows.get("ids", []) or []
            metas = rows.get("metadatas", []) or []
            if not ids:
                return

            sortable: list[tuple[float, str]] = []
            for i, entry_id in enumerate(ids):
                metadata = metas[i] if i < len(metas) else {}
                ts = float((metadata or {}).get("timestamp", 0.0))
                sortable.append((ts, entry_id))

            sortable.sort(key=lambda x: x[0])
            to_delete = [entry_id for _, entry_id in sortable[:overflow] if entry_id]
            if to_delete:
                self._chroma.delete(self._collection, to_delete)
        except Exception as exc:
            logger.warning("semantic_trim_failed", error=str(exc))

    def _migrate_legacy_json_if_needed(self) -> None:
        if not STORE_FILE.exists():
            return

        try:
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            legacy_entries = data.get("entries", [])
        except Exception as exc:
            logger.warning("semantic_migration_read_failed", error=str(exc))
            return

        migrated = 0
        failed = 0
        for entry in legacy_entries:
            entry_id = str(entry.get("id") or uuid.uuid4().hex[:12])
            text = str(entry.get("text") or "")[: self._text_max_len]
            embedding = entry.get("embedding")
            if not text or not isinstance(embedding, list):
                failed += 1
                continue

            metadata = dict(entry.get("metadata") or {})
            metadata = {
                "category": entry.get("category", metadata.get("category", "conversation")),
                "timestamp": float(entry.get("timestamp", metadata.get("timestamp", time.time()))),
                **metadata,
            }
            try:
                self._chroma.store(
                    collection_name=self._collection,
                    doc_id=entry_id,
                    text=text,
                    embedding=embedding,
                    metadata=metadata,
                )
                migrated += 1
            except Exception:
                failed += 1

        migrated_path = STORE_FILE.with_suffix(".json.migrated")
        try:
            STORE_FILE.rename(migrated_path)
        except Exception as exc:
            logger.warning("semantic_migration_rename_failed", error=str(exc))
            return

        logger.info(
            "semantic_memory_migrated",
            source=str(STORE_FILE),
            target=str(migrated_path),
            migrated=migrated,
            failed=failed,
        )
