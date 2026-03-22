"""Marketing KG query layer — provides enrichment context for draft writing."""

import logging
from typing import Dict, List, Optional

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton

logger = logging.getLogger(__name__)


class MarketingKGQuery:
    """Queries the KG for draft enrichment and analytics."""

    def __init__(self, neo4j: Optional[Neo4jSingleton] = None):
        self.neo4j = neo4j or Neo4jSingleton()

    def is_available(self) -> bool:
        """Check if KG is available."""
        return self.neo4j.connected

    async def get_published_posts_on_topic(self, keywords: List[str]) -> List[Dict]:
        """
        Query: What published posts match these keywords?

        Used by draft writer to:
        - Avoid repetition
        - Reference previous work
        - Build on existing content

        Args:
            keywords: List of topic keywords to search for

        Returns:
            List of published posts (title, format, status, published_at)
        """
        if not self.is_available():
            return []

        if not keywords:
            return []

        try:
            cypher = """
            MATCH (p:Post)
            WHERE p.status IN ['approved', 'published']
              AND any(kw IN $keywords WHERE toLower(p.title) CONTAINS toLower(kw))
            RETURN p.title, p.format, p.status, p.published_at
            ORDER BY p.published_at DESC
            LIMIT 5
            """

            results = await self.neo4j.query(cypher, keywords=keywords)
            logger.debug(f"Found {len(results)} published posts for keywords: {keywords}")
            return results

        except Exception as e:
            logger.error(f"Error querying published posts: {e}")
            return []

    async def get_related_orbit_tasks(self, keywords: List[str]) -> List[Dict]:
        """
        Query: What active Orbit tasks relate to these keywords?

        Used to provide project context during draft generation.

        Args:
            keywords: List of keywords to search for in task titles

        Returns:
            List of active Orbit tasks (title, status, priority)
        """
        if not self.is_available():
            return []

        if not keywords:
            return []

        try:
            cypher = """
            MATCH (ot:OrbitTask)
            WHERE ot.status IN ['active', 'in_progress']
              AND any(kw IN $keywords WHERE toLower(ot.title) CONTAINS toLower(kw))
            RETURN ot.title, ot.status, ot.priority
            LIMIT 3
            """

            results = await self.neo4j.query(cypher, keywords=keywords)
            logger.debug(f"Found {len(results)} related Orbit tasks for keywords: {keywords}")
            return results

        except Exception as e:
            logger.error(f"Error querying Orbit tasks: {e}")
            return []

    async def get_pillar_statistics(self, pillar_id: int) -> Dict:
        """
        Query: Statistics for a content pillar.

        Returns:
        - Total post count
        - Published post count
        - Last published date

        Args:
            pillar_id: ContentPillar.id (1-6)

        Returns:
            Dictionary with post_count, published_count, last_published
        """
        if not self.is_available():
            return {"post_count": 0, "published_count": 0, "last_published": None}

        try:
            cypher = """
            MATCH (p:Post)-[:BELONGS_TO]->(cp:ContentPillar {id: $pillar_id})
            RETURN 
              count(p) as post_count,
              count(CASE WHEN p.status = 'published' THEN 1 END) as published_count,
              max(p.published_at) as last_published
            """

            results = await self.neo4j.query(cypher, pillar_id=pillar_id)
            if results:
                return results[0]
            return {"post_count": 0, "published_count": 0, "last_published": None}

        except Exception as e:
            logger.error(f"Error querying pillar statistics: {e}")
            return {"post_count": 0, "published_count": 0, "last_published": None}

    async def get_topic_cluster(self, topic_id: str) -> Optional[Dict]:
        """
        Query: Get a topic's full KG cluster.

        Returns:
        - Topic node properties
        - Connected signals (CONTRIBUTES_TO)
        - Generated posts (GENERATED)

        Args:
            topic_id: Topic node ID

        Returns:
            Dictionary with topic, signals, posts
        """
        if not self.is_available():
            return None

        try:
            cypher = """
            MATCH (t:Topic {id: $topic_id})
            OPTIONAL MATCH (s:Signal)-[:CONTRIBUTES_TO]->(t)
            OPTIONAL MATCH (t)-[:GENERATED]->(p:Post)
            RETURN {
              topic: properties(t),
              signals: collect(DISTINCT properties(s)) FILTER (x IN collect(properties(s)) WHERE x IS NOT NULL),
              posts: collect(DISTINCT properties(p)) FILTER (x IN collect(properties(p)) WHERE x IS NOT NULL)
            } as cluster
            """

            results = await self.neo4j.query(cypher, topic_id=topic_id)
            if results:
                cluster = results[0].get("cluster", {})
                logger.debug(f"Retrieved cluster for topic {topic_id}: {len(cluster.get('signals', []))} signals, {len(cluster.get('posts', []))} posts")
                return cluster
            return None

        except Exception as e:
            logger.error(f"Error querying topic cluster: {e}")
            return None

    async def get_all_pillars_stats(self) -> Dict[int, Dict]:
        """
        Query: Statistics for all 6 content pillars.

        Returns:
            Dictionary mapping pillar_id -> {name, post_count, published_count, last_published}
        """
        if not self.is_available():
            return {}

        try:
            cypher = """
            MATCH (cp:ContentPillar)
            OPTIONAL MATCH (p:Post)-[:BELONGS_TO]->(cp)
            RETURN 
              cp.id as pillar_id,
              cp.name as pillar_name,
              count(p) as post_count,
              count(CASE WHEN p.status = 'published' THEN 1 END) as published_count,
              max(p.published_at) as last_published
            ORDER BY cp.id
            """

            results = await self.neo4j.query(cypher)
            stats = {}
            for row in results:
                pillar_id = row.get("pillar_id")
                if pillar_id:
                    stats[pillar_id] = {
                        "name": row.get("pillar_name"),
                        "post_count": row.get("post_count", 0),
                        "published_count": row.get("published_count", 0),
                        "last_published": row.get("last_published"),
                    }

            logger.debug(f"Retrieved statistics for {len(stats)} pillars")
            return stats

        except Exception as e:
            logger.error(f"Error querying pillar statistics: {e}")
            return {}

    async def get_node_counts(self) -> Dict[str, int]:
        """
        Query: Get counts of all KG node types.

        Returns:
            Dictionary mapping node label -> count
        """
        if not self.is_available():
            return {}

        try:
            cypher = """
            MATCH (n)
            RETURN labels(n)[0] as label, count(n) as count
            GROUP BY labels(n)[0]
            """

            results = await self.neo4j.query(cypher)
            counts = {}
            for row in results:
                label = row.get("label")
                count = row.get("count", 0)
                if label:
                    counts[label] = count

            logger.debug(f"Node counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Error querying node counts: {e}")
            return {}
