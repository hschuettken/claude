"""
Memora Semantic Search Service — ChromaDB-powered vector search for meetings and pages.

Provides semantic search across:
  - Page content (stored as embeddings)
  - Meeting transcripts (segmented and embedded)

Uses sentence-transformers for embedding and ChromaDB for vector storage.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import chromadb
from chromadb.config import Settings
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# Data Models
class SearchResult(BaseModel):
    """A single semantic search result."""
    id: str
    source_type: str  # 'page' or 'transcript'
    source_id: str  # page_id or meeting_id
    segment_index: Optional[int] = None
    text: str
    similarity_score: float
    metadata: dict = {}


class KeywordSearchResult(BaseModel):
    """A single keyword search result."""
    id: str
    source_type: str  # 'page' or 'transcript'
    source_id: str
    segment_index: Optional[int] = None
    text: str
    rank: int
    metadata: dict = {}


class SemanticSearchResponse(BaseModel):
    """Response for semantic search queries."""
    query: str
    results: list[SearchResult]
    count: int
    search_type: str = "semantic"


class KeywordSearchResponse(BaseModel):
    """Response for keyword search queries."""
    query: str
    results: list[KeywordSearchResult]
    count: int
    search_type: str = "keyword"


class SemanticSearchService:
    """Service for semantic and keyword search across pages and transcripts."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        persist_directory: Optional[str] = None,
    ):
        """
        Initialize semantic search service.

        Args:
            model_name: Sentence transformer model name (default: all-MiniLM-L6-v2, ~50MB)
            persist_directory: Path to persist ChromaDB data. If None, uses in-memory.
        """
        self.logger = logging.getLogger(__name__)
        self.model_name = model_name

        # Initialize embeddings model
        self.logger.info(f"Loading embedding model: {model_name}")
        self.embedding_model = SentenceTransformer(model_name)
        self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()
        self.logger.info(f"Embedding dimension: {self.embedding_dim}")

        # Initialize ChromaDB
        if persist_directory:
            persist_directory = os.path.expanduser(persist_directory)
            os.makedirs(persist_directory, exist_ok=True)
            settings = Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=persist_directory,
                anonymized_telemetry=False,
            )
            self.client = chromadb.Client(settings)
            self.logger.info(f"ChromaDB persisting to {persist_directory}")
        else:
            # In-memory ChromaDB
            self.client = chromadb.Client()
            self.logger.info("ChromaDB running in-memory mode")

        # Get or create collections
        self.pages_collection = self.client.get_or_create_collection(
            name="pages",
            metadata={"description": "Page content embeddings"},
        )
        self.transcripts_collection = self.client.get_or_create_collection(
            name="transcripts",
            metadata={"description": "Meeting transcript segment embeddings"},
        )

        self.logger.info("Semantic search service initialized")

    def embed_text(self, text: str) -> list[float]:
        """
        Embed a text string using sentence-transformers.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        embedding = self.embedding_model.encode(text, convert_to_numpy=False)
        return embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)

    def add_page(
        self,
        page_id: str,
        title: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Add a page to the semantic search index.

        Args:
            page_id: Unique page identifier
            title: Page title
            content: Full page content
            metadata: Optional metadata dictionary
        """
        try:
            # Create document by combining title and content
            document = f"{title}\n\n{content}"
            
            # Generate embedding
            embedding = self.embed_text(document)
            
            # Prepare metadata
            meta = metadata or {}
            meta["title"] = title
            meta["source_type"] = "page"
            
            # Add to collection
            self.pages_collection.add(
                ids=[page_id],
                embeddings=[embedding],
                documents=[document],
                metadatas=[meta],
            )
            self.logger.info(f"Added page {page_id} to semantic search index")
        except Exception as e:
            self.logger.error(f"Failed to add page {page_id}: {e}", exc_info=True)
            raise

    def add_transcript(
        self,
        meeting_id: str,
        transcript: str,
        language: str = "en",
        metadata: Optional[dict] = None,
    ) -> int:
        """
        Add a meeting transcript, segmented and embedded.

        Splits long transcripts into chunks to avoid extremely large embeddings.

        Args:
            meeting_id: Unique meeting identifier
            transcript: Full transcript text
            language: Language code
            metadata: Optional metadata dictionary

        Returns:
            Number of segments added
        """
        try:
            # Split transcript into sentences/chunks
            # Simple chunk by sentence (split by . ! ?)
            import re
            sentences = re.split(r'(?<=[.!?])\s+', transcript)
            
            # Group sentences into segments (~5-10 sentences each)
            segment_size = 7
            segments = []
            for i in range(0, len(sentences), segment_size):
                segment = ' '.join(sentences[i:i+segment_size])
                if segment.strip():
                    segments.append(segment)
            
            # Create IDs and embeddings for each segment
            ids = []
            embeddings = []
            documents = []
            metadatas = []
            
            for idx, segment in enumerate(segments):
                # Generate ID
                segment_id = f"{meeting_id}_segment_{idx}"
                ids.append(segment_id)
                
                # Generate embedding
                embedding = self.embed_text(segment)
                embeddings.append(embedding)
                documents.append(segment)
                
                # Prepare metadata
                meta = metadata or {}
                meta["source_type"] = "transcript"
                meta["meeting_id"] = meeting_id
                meta["segment_index"] = idx
                meta["language"] = language
                metadatas.append(meta)
            
            # Add all segments to collection
            if ids:
                self.transcripts_collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )
                self.logger.info(f"Added {len(ids)} segments for meeting {meeting_id}")
            
            return len(ids)
        except Exception as e:
            self.logger.error(f"Failed to add transcript {meeting_id}: {e}", exc_info=True)
            raise

    def semantic_search(
        self,
        query: str,
        source_type: Optional[str] = None,
        top_k: int = 5,
    ) -> SemanticSearchResponse:
        """
        Perform semantic search across pages and/or transcripts.

        Args:
            query: Search query string
            source_type: Filter by 'page' or 'transcript'. If None, search both.
            top_k: Number of results to return

        Returns:
            SemanticSearchResponse with ranked results
        """
        try:
            results = []
            
            # Embed the query
            query_embedding = self.embed_text(query)
            
            # Search pages if not filtered
            if source_type is None or source_type == "page":
                page_results = self.pages_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                )
                
                if page_results and page_results["ids"] and len(page_results["ids"]) > 0:
                    for i, (doc_id, document, metadata, distance) in enumerate(
                        zip(
                            page_results["ids"][0],
                            page_results["documents"][0],
                            page_results["metadatas"][0],
                            page_results["distances"][0],
                        )
                    ):
                        # Convert distance to similarity (1 - normalized distance)
                        similarity = 1 - (distance / 2)  # ChromaDB uses cosine distance 0-2
                        similarity = max(0, min(1, similarity))  # Clamp to [0, 1]
                        
                        results.append(
                            SearchResult(
                                id=doc_id,
                                source_type="page",
                                source_id=doc_id,
                                text=document[:500],  # Truncate for response
                                similarity_score=similarity,
                                metadata=metadata,
                            )
                        )
            
            # Search transcripts if not filtered
            if source_type is None or source_type == "transcript":
                transcript_results = self.transcripts_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                )
                
                if transcript_results and transcript_results["ids"] and len(transcript_results["ids"]) > 0:
                    for i, (doc_id, document, metadata, distance) in enumerate(
                        zip(
                            transcript_results["ids"][0],
                            transcript_results["documents"][0],
                            transcript_results["metadatas"][0],
                            transcript_results["distances"][0],
                        )
                    ):
                        # Convert distance to similarity
                        similarity = 1 - (distance / 2)
                        similarity = max(0, min(1, similarity))
                        
                        results.append(
                            SearchResult(
                                id=doc_id,
                                source_type="transcript",
                                source_id=metadata.get("meeting_id", "unknown"),
                                segment_index=metadata.get("segment_index"),
                                text=document[:500],
                                similarity_score=similarity,
                                metadata=metadata,
                            )
                        )
            
            # Sort by similarity descending and limit
            results.sort(key=lambda r: r.similarity_score, reverse=True)
            results = results[:top_k]
            
            return SemanticSearchResponse(
                query=query,
                results=results,
                count=len(results),
                search_type="semantic",
            )
        except Exception as e:
            self.logger.error(f"Semantic search failed: {e}", exc_info=True)
            raise

    def keyword_search(
        self,
        query: str,
        source_type: Optional[str] = None,
        top_k: int = 5,
    ) -> KeywordSearchResponse:
        """
        Perform keyword-based search across pages and/or transcripts.

        Uses simple substring/word matching.

        Args:
            query: Search query string
            source_type: Filter by 'page' or 'transcript'. If None, search both.
            top_k: Number of results to return

        Returns:
            KeywordSearchResponse with ranked results
        """
        try:
            results = []
            query_lower = query.lower()
            query_words = query_lower.split()
            
            # Search pages if not filtered
            if source_type is None or source_type == "page":
                page_data = self.pages_collection.get(
                    include=["documents", "metadatas"],
                )
                
                if page_data and page_data["ids"]:
                    for doc_id, document, metadata in zip(
                        page_data["ids"],
                        page_data["documents"],
                        page_data["metadatas"],
                    ):
                        # Simple keyword matching: count matching words
                        doc_lower = document.lower()
                        match_count = sum(1 for word in query_words if word in doc_lower)
                        
                        if match_count > 0:
                            results.append({
                                "id": doc_id,
                                "source_type": "page",
                                "source_id": doc_id,
                                "text": document[:500],
                                "match_count": match_count,
                                "metadata": metadata,
                            })
            
            # Search transcripts if not filtered
            if source_type is None or source_type == "transcript":
                transcript_data = self.transcripts_collection.get(
                    include=["documents", "metadatas"],
                )
                
                if transcript_data and transcript_data["ids"]:
                    for doc_id, document, metadata in zip(
                        transcript_data["ids"],
                        transcript_data["documents"],
                        transcript_data["metadatas"],
                    ):
                        # Simple keyword matching
                        doc_lower = document.lower()
                        match_count = sum(1 for word in query_words if word in doc_lower)
                        
                        if match_count > 0:
                            results.append({
                                "id": doc_id,
                                "source_type": "transcript",
                                "source_id": metadata.get("meeting_id", "unknown"),
                                "segment_index": metadata.get("segment_index"),
                                "text": document[:500],
                                "match_count": match_count,
                                "metadata": metadata,
                            })
            
            # Sort by match count descending
            results.sort(key=lambda r: r["match_count"], reverse=True)
            results = results[:top_k]
            
            # Convert to response objects
            response_results = [
                KeywordSearchResult(
                    id=r["id"],
                    source_type=r["source_type"],
                    source_id=r["source_id"],
                    segment_index=r.get("segment_index"),
                    text=r["text"],
                    rank=idx + 1,
                    metadata=r["metadata"],
                )
                for idx, r in enumerate(results)
            ]
            
            return KeywordSearchResponse(
                query=query,
                results=response_results,
                count=len(response_results),
                search_type="keyword",
            )
        except Exception as e:
            self.logger.error(f"Keyword search failed: {e}", exc_info=True)
            raise

    def delete_page(self, page_id: str) -> None:
        """Delete a page from the index."""
        try:
            self.pages_collection.delete(ids=[page_id])
            self.logger.info(f"Deleted page {page_id}")
        except Exception as e:
            self.logger.error(f"Failed to delete page {page_id}: {e}", exc_info=True)

    def delete_transcript(self, meeting_id: str) -> None:
        """Delete all segments for a meeting from the index."""
        try:
            # Query all segments for this meeting and delete
            data = self.transcripts_collection.get(
                where={"meeting_id": {"$eq": meeting_id}},
                include=[],
            )
            if data and data["ids"]:
                self.transcripts_collection.delete(ids=data["ids"])
                self.logger.info(f"Deleted {len(data['ids'])} segments for meeting {meeting_id}")
        except Exception as e:
            self.logger.error(f"Failed to delete transcript {meeting_id}: {e}", exc_info=True)

    def get_stats(self) -> dict:
        """Get collection statistics."""
        try:
            pages_count = self.pages_collection.count()
            transcripts_count = self.transcripts_collection.count()
            
            return {
                "pages": pages_count,
                "transcript_segments": transcripts_count,
                "embedding_model": self.model_name,
                "embedding_dimension": self.embedding_dim,
            }
        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}", exc_info=True)
            return {
                "error": str(e),
            }
