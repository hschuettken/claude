"""Shared ChromaDB client for all homelab services.

Pure-HTTP wrapper — no chromadb pip dependency required.
Uses urllib.request (stdlib) to talk to ChromaDB v2 REST API.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

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

_TENANT_PATH = "/api/v2/tenants/default_tenant/databases/default_database"


class ChromaClient:
    """Pure-HTTP ChromaDB v2 client for homelab services."""

    def __init__(
        self,
        url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self._url = (url or os.getenv("CHROMA_URL", "http://192.168.0.50:8300")).rstrip("/")
        self._auth_token = auth_token or os.getenv("CHROMA_AUTH_TOKEN", "")
        self._headers = {
            "Content-Type": "application/json",
        }
        if self._auth_token:
            self._headers["Authorization"] = f"Bearer {self._auth_token}"
        # Cache: collection name → collection id
        self._collection_ids: dict[str, str] = {}
        logger.info("chroma_client_initialized", url=self._url)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | list | None = None,
    ) -> Any:
        url = f"{self._url}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode()
                if not body.strip():
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if exc.fp else ""
            raise RuntimeError(f"ChromaDB {method} {path} → {exc.code}: {body}") from exc

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def _resolve_collection_id(self, name: str) -> str:
        """Get collection UUID by name, creating it if needed."""
        if name in self._collection_ids:
            return self._collection_ids[name]

        # List existing
        collections = self._request("GET", f"{_TENANT_PATH}/collections")
        if isinstance(collections, list):
            for c in collections:
                self._collection_ids[c["name"]] = c["id"]

        if name in self._collection_ids:
            return self._collection_ids[name]

        # Create
        result = self._request("POST", f"{_TENANT_PATH}/collections", {
            "name": name,
            "metadata": {"hnsw:space": "cosine"},
            "get_or_create": True,
        })
        cid = result["id"]
        self._collection_ids[name] = cid
        logger.info("chroma_collection_created", name=name, id=cid)
        return cid

    def get_collection(self, name: str) -> str:
        """Alias for _resolve_collection_id — returns collection UUID."""
        return self._resolve_collection_id(name)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def store(
        self,
        collection_name: str,
        doc_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a document with pre-computed embedding."""
        cid = self._resolve_collection_id(collection_name)
        self._request("POST", f"{_TENANT_PATH}/collections/{cid}/upsert", {
            "ids": [doc_id],
            "documents": [text],
            "embeddings": [embedding],
            "metadatas": [metadata or {}],
        })

    def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search by embedding vector. Returns list of {id, text, metadata, distance}."""
        cid = self._resolve_collection_id(collection_name)
        payload: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            payload["where"] = where

        try:
            results = self._request("POST", f"{_TENANT_PATH}/collections/{cid}/query", payload)
        except Exception as exc:
            logger.warning("chroma_search_failed", collection=collection_name, error=str(exc))
            return []

        out: list[dict[str, Any]] = []
        ids = (results.get("ids") or [[]])[0]
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        dists = (results.get("distances") or [[]])[0]
        for i, doc_id in enumerate(ids):
            out.append({
                "id": doc_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else 0.0,
            })
        return out

    def delete(self, collection_name: str, ids: list[str]) -> None:
        """Delete documents by ID."""
        cid = self._resolve_collection_id(collection_name)
        self._request("POST", f"{_TENANT_PATH}/collections/{cid}/delete", {"ids": ids})

    def count(self, collection_name: str) -> int:
        """Get document count in a collection."""
        cid = self._resolve_collection_id(collection_name)
        result = self._request("POST", f"{_TENANT_PATH}/collections/{cid}/count", {})
        return int(result) if isinstance(result, (int, float)) else 0

    def bootstrap_collections(self) -> dict[str, int]:
        """Ensure all standard collections exist. Returns {name: count}."""
        result = {}
        for name in ALL_COLLECTIONS:
            self._resolve_collection_id(name)
            try:
                result[name] = self.count(name)
            except Exception:
                result[name] = 0
            logger.info("chroma_bootstrap", collection=name, count=result[name])
        return result

    def heartbeat(self) -> bool:
        """Check if ChromaDB is reachable."""
        try:
            self._request("GET", "/api/v2/heartbeat")
            return True
        except Exception:
            return False
