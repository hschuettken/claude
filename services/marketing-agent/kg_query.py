"""
Knowledge Graph Query Layer for Marketing Agent.

Provides methods to query the NB9OS Knowledge Graph for:
- Published posts related to topics
- Active Orbit tasks/projects
- Content pillar statistics
- Topic clusters (signals + posts graph)
"""
import logging
import os
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketingKGQuery:
    """
    Query interface for marketing entities in the Knowledge Graph.
    
    Attempts to connect to Neo4j via neo4j driver.
    If unavailable, degrades gracefully (draft generation continues without KG context).
    """
    
    def __init__(self):
        """Initialize KG query layer with Neo4j connection."""
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
            logger.warning("NEO4J_PASSWORD not set, KG queries unavailable")
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
            logger.info(f"Connected to KG at {self.neo4j_url}")
            return True
        
        except Exception as e:
            logger.warning(f"Failed to connect to KG: {e}")
            self._available = False
            return False
    
    def is_available(self) -> bool:
        """Check if KG connection is available."""
        return self._available and self._driver is not None
    
    async def get_published_posts_on_topic(self, topic_keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Query: What has Henning published related to these keywords?
        
        Used by draft writer to avoid repetition and provide context.
        
        Args:
            topic_keywords: List of keywords to match against post titles
            
        Returns:
            List of dicts with post metadata (title, format, status, published_at)
        """
        if not self.is_available():
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (p:Post)
                WHERE p.status IN ['approved', 'published']
                  AND any(kw IN $keywords WHERE toLower(p.title) CONTAINS toLower(kw))
                RETURN p.title, p.format, p.status, p.published_at
                ORDER BY p.published_at DESC
                LIMIT 5
                """
                
                result = session.run(cypher, keywords=topic_keywords)
                posts = []
                
                for record in result:
                    posts.append({
                        "title": record["p.title"],
                        "format": record["p.format"],
                        "status": record["p.status"],
                        "published_at": record["p.published_at"],
                    })
                
                logger.info(f"Found {len(posts)} published posts for keywords: {topic_keywords}")
                return posts
        
        except Exception as e:
            logger.error(f"Error querying published posts: {e}")
            return []
    
    async def get_active_projects(self, topic_keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Query: What Orbit tasks/projects relate to this topic?
        
        Provides context about active work that might be mentioned in drafts.
        
        Args:
            topic_keywords: List of keywords to match against task titles
            
        Returns:
            List of dicts with task metadata (title, status, priority)
        """
        if not self.is_available():
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (ot:OrbitTask)
                WHERE ot.status IN ['active', 'in_progress']
                  AND any(kw IN $keywords WHERE toLower(ot.title) CONTAINS toLower(kw))
                RETURN ot.title, ot.status, ot.priority
                LIMIT 3
                """
                
                result = session.run(cypher, keywords=topic_keywords)
                tasks = []
                
                for record in result:
                    tasks.append({
                        "title": record["ot.title"],
                        "status": record["ot.status"],
                        "priority": record["ot.priority"],
                    })
                
                logger.info(f"Found {len(tasks)} active projects for keywords: {topic_keywords}")
                return tasks
        
        except Exception as e:
            logger.error(f"Error querying active projects: {e}")
            return []
    
    async def get_pillar_statistics(self, pillar_id: int) -> Dict[str, Any]:
        """
        Query: How much content has been created for this pillar?
        
        Returns statistics like post count, last published date, etc.
        
        Args:
            pillar_id: Content pillar ID (1-6)
            
        Returns:
            Dict with keys: post_count, published_count, last_published
        """
        if not self.is_available():
            return {"post_count": 0, "published_count": 0, "last_published": None}
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (p:Post)-[:BELONGS_TO]->(cp:ContentPillar {id: $pillar_id})
                RETURN 
                  count(p) as post_count,
                  count(CASE WHEN p.status = 'published' THEN 1 END) as published_count,
                  max(p.published_at) as last_published
                """
                
                result = session.run(cypher, pillar_id=pillar_id)
                record = result.single()
                
                if record:
                    stats = {
                        "post_count": record["post_count"] or 0,
                        "published_count": record["published_count"] or 0,
                        "last_published": record["last_published"],
                    }
                    logger.info(f"Pillar {pillar_id} stats: {stats}")
                    return stats
                
                return {"post_count": 0, "published_count": 0, "last_published": None}
        
        except Exception as e:
            logger.error(f"Error querying pillar statistics: {e}")
            return {"post_count": 0, "published_count": 0, "last_published": None}
    
    async def get_topic_cluster(self, topic_id: str) -> Dict[str, Any]:
        """
        Query: Get a topic's full KG cluster.
        
        Returns the topic node plus its related signals and generated posts.
        
        Args:
            topic_id: Topic node ID
            
        Returns:
            Dict with keys: topic, signals, posts
        """
        if not self.is_available():
            return {"topic": None, "signals": [], "posts": []}
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (t:Topic {id: $topic_id})
                OPTIONAL MATCH (s:Signal)-[:CONTRIBUTES_TO]->(t)
                OPTIONAL MATCH (t)-[:GENERATED]->(p:Post)
                RETURN t, collect(DISTINCT s) as signals, collect(DISTINCT p) as posts
                """
                
                result = session.run(cypher, topic_id=topic_id)
                record = result.single()
                
                if record:
                    return {
                        "topic": dict(record["t"]) if record["t"] else None,
                        "signals": [dict(s) for s in (record["signals"] or [])],
                        "posts": [dict(p) for p in (record["posts"] or [])],
                    }
                
                return {"topic": None, "signals": [], "posts": []}
        
        except Exception as e:
            logger.error(f"Error querying topic cluster: {e}")
            return {"topic": None, "signals": [], "posts": []}
    
    def close(self):
        """Close Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._available = False
            logger.info("Closed KG connection")


# Global singleton instance
_kg_query_instance: Optional[MarketingKGQuery] = None


def get_kg_query() -> MarketingKGQuery:
    """Get or create the global KG query instance."""
    global _kg_query_instance
    if _kg_query_instance is None:
        _kg_query_instance = MarketingKGQuery()
    return _kg_query_instance
