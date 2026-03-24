"""
Knowledge Graph Ingestion for Marketing Agent.

Auto-syncs marketing entities (Signals, Topics, Drafts) to the NB9OS Knowledge Graph.
Uses Neo4j driver for direct writes when REST API not available.

Gracefully degrades if KG unavailable — ingestion failures don't break marketing operations.
"""
import logging
import os
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketingKGIngestion:
    """
    Writes marketing entities to the NB9OS Knowledge Graph.
    
    Provides methods to ingest:
    - Signals → Signal nodes
    - Topics → Topic nodes + CONTRIBUTES_TO relationships
    - Drafts → Post nodes + relationships
    """
    
    def __init__(self):
        """Initialize ingestion layer with Neo4j connection."""
        self.neo4j_url = os.getenv("NEO4J_URL", "bolt://192.168.0.340:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "")
        
        self._driver = None
        self._available = False
        
        # Try to connect on init
        self._ensure_connected()
    
    def _ensure_connected(self) -> bool:
        """
        Lazy connect to Neo4j.
        Returns True if connected, False otherwise.
        """
        if self._available:
            return True
        
        if not self.neo4j_password:
            logger.warning("NEO4J_PASSWORD not set, KG ingestion unavailable")
            return False
        
        try:
            from neo4j import GraphDatabase
            
            self._driver = GraphDatabase.driver(
                self.neo4j_url,
                auth=(self.neo4j_user, self.neo4j_password),
                connection_timeout=5,
            )
            
            # Test connection
            with self._driver.session() as session:
                session.run("RETURN 1")
            
            self._available = True
            logger.info(f"Connected to KG at {self.neo4j_url} for ingestion")
            return True
        
        except Exception as e:
            logger.warning(f"Failed to connect to KG for ingestion: {e}")
            self._available = False
            return False
    
    def is_available(self) -> bool:
        """Check if KG connection is available."""
        return self._available and self._driver is not None
    
    async def ingest_signal(self, signal_id: int, title: str, url: str, 
                           pillar_id: Optional[int], relevance_score: float) -> bool:
        """
        Write a Signal node to the KG.
        
        Called after signal is detected and saved to marketing.signals.
        
        Args:
            signal_id: Marketing signals.id
            title: Signal title
            url: Source URL
            pillar_id: Associated content pillar ID
            relevance_score: Relevance score (0.0-1.0)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.debug("KG unavailable, skipping signal ingestion")
            return False
        
        try:
            with self._driver.session() as session:
                cypher = """
                MERGE (s:Signal {id: $signal_id})
                SET s.title = $title,
                    s.url = $url,
                    s.pillar_id = $pillar_id,
                    s.relevance_score = $relevance_score,
                    s.detected_at = datetime(),
                    s.status = 'active',
                    s.updated_at = datetime()
                RETURN s.id
                """
                
                result = session.run(
                    cypher,
                    signal_id=str(signal_id),
                    title=title,
                    url=url,
                    pillar_id=pillar_id,
                    relevance_score=relevance_score,
                )
                
                record = result.single()
                if record:
                    logger.info(f"Ingested Signal {signal_id}: {title}")
                    
                    # Link to pillar if available
                    if pillar_id:
                        self._create_relationship(
                            from_label="Signal", from_id=str(signal_id),
                            rel="BELONGS_TO",
                            to_label="ContentPillar", to_id=str(pillar_id)
                        )
                    
                    return True
        
        except Exception as e:
            logger.error(f"Failed to ingest signal {signal_id}: {e}")
        
        return False
    
    async def ingest_topic(self, topic_id: int, title: str, summary: Optional[str],
                          pillar_id: Optional[int], score: float, signal_ids: List[int]) -> bool:
        """
        Write a Topic node to the KG.
        
        Called after topic is scored and saved to marketing.topics.
        Links related signals via CONTRIBUTES_TO relationships.
        
        Args:
            topic_id: Marketing topics.id
            title: Topic title
            summary: Topic summary/description
            pillar_id: Associated content pillar ID
            score: Topic score
            signal_ids: List of signal IDs that contributed to this topic
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.debug("KG unavailable, skipping topic ingestion")
            return False
        
        try:
            with self._driver.session() as session:
                cypher = """
                MERGE (t:Topic {id: $topic_id})
                SET t.title = $title,
                    t.summary = $summary,
                    t.pillar_id = $pillar_id,
                    t.score = $score,
                    t.status = 'active',
                    t.created_at = datetime(),
                    t.updated_at = datetime()
                RETURN t.id
                """
                
                result = session.run(
                    cypher,
                    topic_id=str(topic_id),
                    title=title,
                    summary=summary or "",
                    pillar_id=pillar_id,
                    score=float(score),
                )
                
                record = result.single()
                if record:
                    logger.info(f"Ingested Topic {topic_id}: {title}")
                    
                    # Link signals to topic via CONTRIBUTES_TO
                    for signal_id in signal_ids:
                        self._create_relationship(
                            from_label="Signal", from_id=str(signal_id),
                            rel="CONTRIBUTES_TO",
                            to_label="Topic", to_id=str(topic_id)
                        )
                    
                    # Link to pillar if available
                    if pillar_id:
                        self._create_relationship(
                            from_label="Topic", from_id=str(topic_id),
                            rel="BELONGS_TO",
                            to_label="ContentPillar", to_id=str(pillar_id)
                        )
                    
                    return True
        
        except Exception as e:
            logger.error(f"Failed to ingest topic {topic_id}: {e}")
        
        return False
    
    async def ingest_draft_as_post(self, draft_id: int, title: str, format: str,
                                   topic_id: Optional[int], pillar_id: Optional[int],
                                   word_count: int, status: str) -> bool:
        """
        Write a Draft as Post node to the KG.
        
        Called when draft is created or status changes.
        Links to topic if available.
        
        Args:
            draft_id: Marketing drafts.id
            title: Draft title
            format: Format (blog, linkedin_teaser, linkedin_native)
            topic_id: Associated topic ID (if any)
            pillar_id: Associated content pillar ID
            word_count: Word count of draft content
            status: Draft status (draft, review, approved, published)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.debug("KG unavailable, skipping draft ingestion")
            return False
        
        try:
            with self._driver.session() as session:
                cypher = """
                MERGE (p:Post {id: $draft_id})
                SET p.title = $title,
                    p.format = $format,
                    p.pillar_id = $pillar_id,
                    p.word_count = $word_count,
                    p.status = $status,
                    p.created_at = datetime(),
                    p.updated_at = datetime()
                RETURN p.id
                """
                
                result = session.run(
                    cypher,
                    draft_id=str(draft_id),
                    title=title,
                    format=format,
                    pillar_id=pillar_id,
                    word_count=word_count,
                    status=status,
                )
                
                record = result.single()
                if record:
                    logger.info(f"Ingested Post {draft_id}: {title}")
                    
                    # Link to topic if available
                    if topic_id:
                        self._create_relationship(
                            from_label="Topic", from_id=str(topic_id),
                            rel="GENERATED",
                            to_label="Post", to_id=str(draft_id)
                        )
                    
                    # Link to pillar if available
                    if pillar_id:
                        self._create_relationship(
                            from_label="Post", from_id=str(draft_id),
                            rel="BELONGS_TO",
                            to_label="ContentPillar", to_id=str(pillar_id)
                        )
                    
                    return True
        
        except Exception as e:
            logger.error(f"Failed to ingest draft {draft_id}: {e}")
        
        return False
    
    def _create_relationship(self, from_label: str, from_id: str, rel: str,
                            to_label: str, to_id: str) -> bool:
        """
        Create or update a relationship between two nodes.
        
        Args:
            from_label: Source node label (Signal, Topic, Post, etc.)
            from_id: Source node ID
            rel: Relationship type (CONTRIBUTES_TO, GENERATED, BELONGS_TO, etc.)
            to_label: Target node label
            to_id: Target node ID
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            with self._driver.session() as session:
                cypher = f"""
                MATCH (from:{from_label} {{id: $from_id}})
                MATCH (to:{to_label} {{id: $to_id}})
                MERGE (from)-[r:{rel}]->(to)
                SET r.created_at = datetime()
                RETURN r
                """
                
                result = session.run(
                    cypher,
                    from_id=from_id,
                    to_id=to_id,
                )
                
                if result.single():
                    logger.debug(f"Created relationship {from_label}-[{rel}]->{to_label}")
                    return True
        
        except Exception as e:
            logger.warning(f"Failed to create relationship: {e}")
        
        return False
    
    def close(self):
        """Close Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._available = False
            logger.info("Closed KG ingestion connection")


# Global singleton instance
_kg_ingest_instance: Optional[MarketingKGIngestion] = None


def get_kg_ingest() -> MarketingKGIngestion:
    """Get or create the global KG ingestion instance."""
    global _kg_ingest_instance
    if _kg_ingest_instance is None:
        _kg_ingest_instance = MarketingKGIngestion()
    return _kg_ingest_instance
