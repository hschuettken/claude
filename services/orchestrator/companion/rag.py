"""Parallel RAG fan-out with Reciprocal Rank Fusion (RRF) for Kairos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Optional

import asyncpg
import httpx
import redis.asyncio as redis
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# RRF constant (standard value)
RRF_K = 60


class RetrievalChunk(BaseModel):
    """A single chunk retrieved from a source."""

    source: str  # "graphrag", "scout", "oracle", "history", "hot_state"
    content: str  # text content
    score: float  # RRF combined score
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Result of a retrieval operation with sources and hot state."""

    chunks: list[RetrievalChunk]
    sources_queried: list[str]
    sources_succeeded: list[str]
    query: str
    hot_state: dict[str, Any] = Field(default_factory=dict)


class RAGEngine:
    """
    Parallel RAG fan-out with Reciprocal Rank Fusion (RRF).

    Queries multiple sources (GraphRAG, Scout, Oracle, history, hot state) in parallel,
    deduplicates by content hash, and fuses results using RRF.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        pool: asyncpg.Pool,
        nb9os_token: str = "",
        oracle_url: str = "http://192.168.0.50:8225",
        scout_url: str = "http://192.168.0.50:8888",
        graphrag_url: str = "http://192.168.0.50:8060/api/v1/graph-rag/search",
    ):
        """
        Initialize RAG engine.

        Args:
            redis_client: redis.asyncio client for hot state access
            pool: asyncpg connection pool for Postgres access
            nb9os_token: JWT token for nb9os API calls (GraphRAG)
            oracle_url: Integration Oracle base URL
            scout_url: Scout/WebSearch base URL
            graphrag_url: GraphRAG search endpoint
        """
        self.redis_client = redis_client
        self.pool = pool
        self.nb9os_token = nb9os_token
        self.oracle_url = oracle_url
        self.scout_url = scout_url
        self.graphrag_url = graphrag_url
        self._http_timeout = 15.0

    async def retrieve(
        self,
        query: str,
        user_id: str = "default",
        session_id: Optional[str] = None,
        sources: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        """
        Fan out to all enabled sources in parallel, fuse results with RRF.

        Args:
            query: Search query
            user_id: User ID for hot state access
            session_id: Optional session ID for conversation history
            sources: If None, use all. Options: ["graphrag", "scout", "oracle", "history", "hot_state"]
            top_k: Number of top results to return

        Returns:
            RetrievalResult with fused chunks, sources queried, and sources succeeded
        """
        # Default to all sources if not specified
        if sources is None:
            sources = ["graphrag", "scout", "oracle", "history", "hot_state"]

        logger.info(
            "rag_retrieve_start",
            query=query,
            user_id=user_id,
            session_id=session_id,
            sources=sources,
            top_k=top_k,
        )

        # Prepare tasks for each source
        tasks = []
        source_names = []

        if "graphrag" in sources:
            tasks.append(self._fetch_graphrag(query))
            source_names.append("graphrag")

        if "scout" in sources:
            tasks.append(self._fetch_scout(query))
            source_names.append("scout")

        if "oracle" in sources:
            tasks.append(self._fetch_oracle(query))
            source_names.append("oracle")

        if "history" in sources and session_id:
            tasks.append(self._fetch_history(session_id))
            source_names.append("history")

        if "hot_state" in sources:
            tasks.append(self._fetch_hot_state(user_id))
            source_names.append("hot_state")

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and track successes
        all_chunks: list[tuple[str, RetrievalChunk]] = []  # (source, chunk)
        hot_state_dict: dict[str, Any] = {}
        sources_succeeded: list[str] = []

        for i, result in enumerate(results):
            source = source_names[i]

            # Handle exceptions
            if isinstance(result, Exception):
                logger.warning(
                    "rag_source_failed",
                    source=source,
                    error=str(result),
                    query=query,
                )
                continue

            # Unpack result
            chunks, maybe_hot_state = result
            sources_succeeded.append(source)

            # Add chunks with source attribution
            for chunk in chunks:
                chunk.source = source
                all_chunks.append((source, chunk))

            # Capture hot state if present
            if maybe_hot_state:
                hot_state_dict = maybe_hot_state

        logger.info(
            "rag_sources_completed",
            query=query,
            sources_succeeded=sources_succeeded,
            total_chunks_before_dedup=len(all_chunks),
        )

        # Deduplication by content hash (first 100 chars)
        deduped: dict[str, tuple[str, RetrievalChunk]] = {}  # hash -> (source, chunk)
        for source, chunk in all_chunks:
            # Hash first 100 chars of content
            hash_key = hashlib.md5(chunk.content[:100].encode()).hexdigest()
            if hash_key not in deduped:
                deduped[hash_key] = (source, chunk)
            # Keep existing entry (preserves best per-source rank)

        logger.info("rag_deduplication_complete", chunks_after_dedup=len(deduped))

        # Perform RRF fusion
        fused_chunks = self._fuse_with_rrf(deduped, top_k)

        logger.info(
            "rag_retrieve_complete",
            query=query,
            chunks_returned=len(fused_chunks),
            sources_succeeded=sources_succeeded,
        )

        return RetrievalResult(
            chunks=fused_chunks,
            sources_queried=source_names,
            sources_succeeded=sources_succeeded,
            query=query,
            hot_state=hot_state_dict,
        )

    async def _fetch_graphrag(
        self, query: str
    ) -> tuple[list[RetrievalChunk], Optional[dict[str, Any]]]:
        """
        Fetch from GraphRAG.

        Returns: (list of chunks, None)
        """
        try:
            headers = {}
            if self.nb9os_token:
                headers["Authorization"] = f"Bearer {self.nb9os_token}"

            payload = {"query": query, "k": 10}

            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.post(
                    self.graphrag_url,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            # Expected response: list of {content, score, metadata}
            chunks: list[RetrievalChunk] = []
            if isinstance(data, list):
                for i, item in enumerate(data):
                    chunk = RetrievalChunk(
                        source="graphrag",
                        content=item.get("content", ""),
                        score=float(item.get("score", 0.0)),
                        metadata=item.get("metadata", {}),
                    )
                    chunks.append(chunk)
            elif isinstance(data, dict) and "results" in data:
                # Alternative response format
                for i, item in enumerate(data["results"]):
                    chunk = RetrievalChunk(
                        source="graphrag",
                        content=item.get("content", ""),
                        score=float(item.get("score", 0.0)),
                        metadata=item.get("metadata", {}),
                    )
                    chunks.append(chunk)

            logger.debug("graphrag_fetch_success", query=query, chunks=len(chunks))
            return chunks, None

        except Exception as e:
            logger.error("graphrag_fetch_failed", query=query, error=str(e))
            return [], None

    async def _fetch_scout(
        self, query: str
    ) -> tuple[list[RetrievalChunk], Optional[dict[str, Any]]]:
        """
        Fetch from Scout/WebSearch.

        Returns: (list of chunks, None)
        """
        try:
            payload = {"query": query, "max_results": 10}

            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.post(
                    f"{self.scout_url}/search",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Expected response: {results: [{title, link, content, ...}]} or similar
            chunks: list[RetrievalChunk] = []
            results = data.get("results", []) if isinstance(data, dict) else data

            for i, item in enumerate(results):
                # Scout returns title + content + link
                content = item.get("content") or item.get("body") or ""
                title = item.get("title", "")
                link = item.get("link", item.get("url", ""))

                if title:
                    content = f"{title}\n{content}"

                chunk = RetrievalChunk(
                    source="scout",
                    content=content.strip(),
                    score=float(item.get("score", 0.0)),
                    metadata={"link": link} if link else {},
                )
                if chunk.content:  # Skip empty chunks
                    chunks.append(chunk)

            logger.debug("scout_fetch_success", query=query, chunks=len(chunks))
            return chunks, None

        except Exception as e:
            logger.error("scout_fetch_failed", query=query, error=str(e))
            return [], None

    async def _fetch_oracle(
        self, query: str
    ) -> tuple[list[RetrievalChunk], Optional[dict[str, Any]]]:
        """
        Fetch from Integration Oracle.

        Returns: (list with single oracle response chunk, None)
        """
        try:
            payload = {"intent": query}

            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.post(
                    f"{self.oracle_url}/oracle/query",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Oracle returns {services: [...], guidance: "...", nats_events: [...]}
            # Wrap entire response as a single chunk
            guidance = data.get("guidance", "")
            if not guidance:
                # Fallback: convert dict to string
                guidance = json.dumps(data)

            chunk = RetrievalChunk(
                source="oracle",
                content=guidance,
                score=1.0,  # Oracle is authoritative
                metadata=data,
            )

            logger.debug("oracle_fetch_success", query=query)
            return [chunk], None

        except Exception as e:
            logger.error("oracle_fetch_failed", query=query, error=str(e))
            return [], None

    async def _fetch_history(
        self, session_id: str
    ) -> tuple[list[RetrievalChunk], Optional[dict[str, Any]]]:
        """
        Fetch conversation history from Postgres.

        Returns: (list of chunks, None)
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, role, content, created_at
                    FROM companion.messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    session_id,
                )

            chunks: list[RetrievalChunk] = []
            for i, row in enumerate(rows):
                # Format as "role: content"
                content = f"{row['role']}: {row['content'][:200]}"

                chunk = RetrievalChunk(
                    source="history",
                    content=content,
                    score=1.0,  # Equal weight for history
                    metadata={
                        "message_id": str(row["id"]),
                        "created_at": row["created_at"].isoformat(),
                    },
                )
                chunks.append(chunk)

            logger.debug(
                "history_fetch_success",
                session_id=session_id,
                chunks=len(chunks),
            )
            return chunks, None

        except Exception as e:
            logger.error("history_fetch_failed", session_id=session_id, error=str(e))
            return [], None

    async def _fetch_hot_state(
        self, user_id: str
    ) -> tuple[list[RetrievalChunk], Optional[dict[str, Any]]]:
        """
        Fetch hot state from Redis.

        Returns: (list with single hot state chunk, dict of hot state)
        """
        try:
            key = f"kairos:hot_state:{user_id}"
            data = await self.redis_client.get(key)

            if not data:
                logger.debug("hot_state_not_found", user_id=user_id)
                return [], None

            hot_state_dict = json.loads(data)

            # Convert to JSON string for content
            content = json.dumps(hot_state_dict, indent=2)

            chunk = RetrievalChunk(
                source="hot_state",
                content=content,
                score=1.0,  # Hot state is current and authoritative
                metadata={"user_id": user_id},
            )

            logger.debug("hot_state_fetch_success", user_id=user_id)
            return [chunk], hot_state_dict

        except Exception as e:
            logger.error("hot_state_fetch_failed", user_id=user_id, error=str(e))
            return [], None

    def _fuse_with_rrf(
        self,
        deduped: dict[str, tuple[str, RetrievalChunk]],
        top_k: int,
    ) -> list[RetrievalChunk]:
        """
        Fuse deduplicated chunks using Reciprocal Rank Fusion (RRF).

        RRF score = sum over sources of: 1 / (RRF_K + rank)

        Args:
            deduped: Dict of {hash -> (source, chunk)}
            top_k: Number of top results to return

        Returns:
            Sorted list of top_k chunks with fused scores
        """
        # Group chunks by source and rank them
        source_chunks: dict[str, list[RetrievalChunk]] = {}
        for hash_key, (source, chunk) in deduped.items():
            if source not in source_chunks:
                source_chunks[source] = []
            source_chunks[source].append(chunk)

        # Compute RRF scores
        rrf_scores: dict[str, float] = {}

        for source, chunks in source_chunks.items():
            for rank, chunk in enumerate(chunks, start=1):
                # Find the chunk in deduped and compute its hash
                hash_key = hashlib.md5(chunk.content[:100].encode()).hexdigest()

                if hash_key not in rrf_scores:
                    rrf_scores[hash_key] = 0.0

                # Add RRF contribution from this source
                rrf_score = 1.0 / (RRF_K + rank)
                rrf_scores[hash_key] += rrf_score

        # Sort by RRF score
        sorted_hashes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        # Reconstruct chunks with new scores
        result: list[RetrievalChunk] = []
        for hash_key, score in sorted_hashes[:top_k]:
            source, chunk = deduped[hash_key]
            # Update score to RRF score
            chunk.score = score
            result.append(chunk)

        logger.debug(
            "rrf_fusion_complete",
            chunks_input=len(deduped),
            chunks_output=len(result),
            rrf_k=RRF_K,
        )

        return result
