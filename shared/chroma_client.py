"""Shared ChromaDB client for all homelab services.

Provides a thin wrapper around chromadb.HttpClient with:
- Auto-creation of collections on first access
- Auth token from environment
- Consistent collection naming
"""

import os
from typing import Any
from urllib.parse import urlparse

import chromadb
from chromadb.config import Settings

from shared.log import get_logger

logger = get_logger("chroma_client")

# Collection names (canonical)
COLLECTION_ORCHESTRATOR_MEMORY = "orchestrator_memory"
COLLECTION_HOMELAB_KNOWLEDGE = "homelab_knowledge"
COLLECTION_MONITORING_EVENTS = "monitoring_events"
COLLECTION_AGENT_CONTEXT = "agent_context"

ALL_COLLECTIONS = [
    COLLECTION_ORCHESTRATOR_MEMORY,
    COLLECTION_HOMELAB_KNOWLEDGE,
    COLLECTION_MONITORING_EVENTS,
    COLLECTION_AGENT_CONTEXT,
]


class ChromaClient:
    """Wrapper around chromadb.HttpClient for homelab services."""

    def __init__(
        self,
        url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self._url = url or os.getenv("CHROMA_URL", "http://192.168.0.50:8300")
        self._auth_token = auth_token or os.getenv("CHROMA_AUTH_TOKEN", "")

        parsed = urlparse(self._url)
        host = parsed.hostname or "192.168.0.50"
        port = parsed.port or 8300

        settings = (
            Settings(
                chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
                chroma_client_auth_credentials=self._auth_token,
            )
            if self._auth_token
            else Settings()
        )

        self._client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=settings,
        )
        self._collections: dict[str, Any] = {}
        logger.info("chroma_client_initialized", url=self._url)

    @property
    def client(self) -> chromadb.HttpClient:
        return self._client

    def get_collection(self, name: str) -> Any:
        """Get or create a collection by name."""
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("chroma_collection_ready", name=name)
        return self._collections[name]

    def store(
        self,
        collection_name: str,
        doc_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a document with pre-computed embedding."""
        coll = self.get_collection(collection_name)
        coll.upsert(
            ids=[doc_id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata or {}],
        )

    def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search by embedding vector. Returns list of {id, text, metadata, distance}."""
        coll = self.get_collection(collection_name)
        count = coll.count()
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, count) if count > 0 else top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            results = coll.query(**kwargs)
        except Exception as exc:
            logger.warning(
                "chroma_search_failed", collection=collection_name, error=str(exc)
            )
            return []

        out: list[dict[str, Any]] = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                out.append(
                    {
                        "id": doc_id,
                        "text": results["documents"][0][i] if results["documents"] else "",
                        "metadata": (
                            results["metadatas"][0][i] if results["metadatas"] else {}
                        ),
                        "distance": (
                            results["distances"][0][i] if results["distances"] else 0.0
                        ),
                    }
                )
        return out

    def delete(self, collection_name: str, ids: list[str]) -> None:
        """Delete documents by ID."""
        coll = self.get_collection(collection_name)
        coll.delete(ids=ids)

    def count(self, collection_name: str) -> int:
        """Get document count in a collection."""
        return self.get_collection(collection_name).count()

    def bootstrap_collections(self) -> dict[str, int]:
        """Ensure all standard collections exist. Returns {name: count}."""
        result = {}
        for name in ALL_COLLECTIONS:
            coll = self.get_collection(name)
            result[name] = coll.count()
            logger.info("chroma_bootstrap", collection=name, count=coll.count())
        return result

    def heartbeat(self) -> bool:
        """Check if ChromaDB is reachable."""
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False
