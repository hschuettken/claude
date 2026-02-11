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
"""

from __future__ import annotations

import asyncio
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

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        result = await asyncio.to_thread(
            genai.embed_content,
            model="models/text-embedding-004",
            content=text,
        )
        return result["embedding"]

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
        """Semantic search — return the most relevant past entries."""
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

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in candidates:
            sim = _cosine_similarity(query_embedding, entry["embedding"])
            scored.append((sim, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for score, entry in scored[:top_k]:
            results.append({
                "id": entry["id"],
                "text": entry["text"],
                "category": entry["category"],
                "metadata": entry["metadata"],
                "similarity": round(score, 3),
                "age_days": round((time.time() - entry["timestamp"]) / 86400, 1),
            })
        return results

    @property
    def entry_count(self) -> int:
        return len(self._entries)

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
