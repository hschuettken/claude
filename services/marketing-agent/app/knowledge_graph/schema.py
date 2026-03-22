"""Neo4j Knowledge Graph schema definitions for marketing entities."""

import logging
from typing import Optional

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton

logger = logging.getLogger(__name__)


class MarketingKGSchema:
    """Schema initialization and constraint management for marketing KG entities."""

    # Cypher constraints for Signal nodes
    SIGNAL_CONSTRAINTS = [
        "CREATE CONSTRAINT signal_id IF NOT EXISTS FOR (s:Signal) REQUIRE s.id IS UNIQUE",
        "CREATE INDEX signal_title IF NOT EXISTS FOR (s:Signal) ON (s.title)",
        "CREATE INDEX signal_pillar IF NOT EXISTS FOR (s:Signal) ON (s.pillar_id)",
        "CREATE INDEX signal_status IF NOT EXISTS FOR (s:Signal) ON (s.status)",
    ]

    # Cypher constraints for Topic nodes
    TOPIC_CONSTRAINTS = [
        "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
        "CREATE INDEX topic_title IF NOT EXISTS FOR (t:Topic) ON (t.title)",
        "CREATE INDEX topic_pillar IF NOT EXISTS FOR (t:Topic) ON (t.pillar_id)",
        "CREATE INDEX topic_status IF NOT EXISTS FOR (t:Topic) ON (t.status)",
    ]

    # Cypher constraints for Post nodes
    POST_CONSTRAINTS = [
        "CREATE CONSTRAINT post_id IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE",
        "CREATE INDEX post_title IF NOT EXISTS FOR (p:Post) ON (p.title)",
        "CREATE INDEX post_format IF NOT EXISTS FOR (p:Post) ON (p.format)",
        "CREATE INDEX post_status IF NOT EXISTS FOR (p:Post) ON (p.status)",
        "CREATE INDEX post_pillar IF NOT EXISTS FOR (p:Post) ON (p.pillar_id)",
    ]

    # Cypher constraints for ContentPillar nodes
    PILLAR_CONSTRAINTS = [
        "CREATE CONSTRAINT pillar_id IF NOT EXISTS FOR (cp:ContentPillar) REQUIRE cp.id IS UNIQUE",
        "CREATE INDEX pillar_name IF NOT EXISTS FOR (cp:ContentPillar) ON (cp.name)",
    ]

    ALL_CONSTRAINTS = (
        SIGNAL_CONSTRAINTS
        + TOPIC_CONSTRAINTS
        + POST_CONSTRAINTS
        + PILLAR_CONSTRAINTS
    )

    @staticmethod
    async def initialize(neo4j: Optional[Neo4jSingleton] = None) -> bool:
        """
        Initialize all KG schema constraints.

        Returns:
            True if initialization successful, False if KG unavailable.
        """
        if neo4j is None:
            neo4j = await Neo4jSingleton().initialize("", "", "")

        if not neo4j.connected:
            logger.warning("KG schema initialization skipped (Neo4j not connected)")
            return False

        success_count = 0
        for constraint in MarketingKGSchema.ALL_CONSTRAINTS:
            try:
                await neo4j.execute(constraint)
                success_count += 1
                logger.debug(f"Created constraint: {constraint[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to create constraint: {e}")

        logger.info(
            f"✓ KG schema initialized: {success_count}/{len(MarketingKGSchema.ALL_CONSTRAINTS)} constraints"
        )
        return success_count > 0

    @staticmethod
    async def seed_pillars(neo4j: Optional[Neo4jSingleton] = None) -> bool:
        """
        Seed ContentPillar nodes (6 pillars defined in spec).

        Returns:
            True if seeding successful, False if KG unavailable.
        """
        if neo4j is None:
            neo4j = await Neo4jSingleton().initialize("", "", "")

        if not neo4j.connected:
            logger.warning("ContentPillar seeding skipped (Neo4j not connected)")
            return False

        pillars = [
            {"id": 1, "name": "SAP deep technical", "weight": 0.45},
            {"id": 2, "name": "SAP roadmap & features", "weight": 0.20},
            {"id": 3, "name": "Architecture & decisions", "weight": 0.15},
            {"id": 4, "name": "AI in the enterprise", "weight": 0.10},
            {"id": 5, "name": "Builder / lab / infrastructure", "weight": 0.07},
            {"id": 6, "name": "Personal builder lifestyle", "weight": 0.03},
        ]

        cypher = """
        MERGE (cp:ContentPillar {id: $id})
        SET cp.name = $name,
            cp.weight = $weight,
            cp.updated_at = datetime()
        RETURN cp.id
        """

        success_count = 0
        for pillar in pillars:
            try:
                await neo4j.execute(cypher, **pillar)
                success_count += 1
                logger.debug(f"Seeded pillar: {pillar['name']}")
            except Exception as e:
                logger.warning(f"Failed to seed pillar {pillar['id']}: {e}")

        logger.info(f"✓ ContentPillar seeding: {success_count}/{len(pillars)} pillars")
        return success_count == len(pillars)


# Node properties documentation (for reference)
NODE_PROPERTIES = {
    "Signal": {
        "id": "str (unique)",
        "title": "str",
        "url": "str",
        "pillar_id": "int",
        "relevance_score": "float",
        "detected_at": "ISO datetime string",
        "status": "str (new, read, used, archived)",
        "created_at": "ISO datetime string",
        "updated_at": "ISO datetime string",
    },
    "Topic": {
        "id": "str (unique)",
        "title": "str",
        "summary": "str",
        "pillar_id": "int",
        "score": "float (0.0-1.0)",
        "status": "str (candidate, selected, drafted, published, archived)",
        "created_at": "ISO datetime string",
        "updated_at": "ISO datetime string",
    },
    "Post": {
        "id": "str (unique)",
        "title": "str",
        "format": "str (blog, linkedin_teaser, linkedin_native)",
        "pillar_id": "int",
        "word_count": "int",
        "status": "str (draft, review, approved, published)",
        "published_at": "ISO datetime string (nullable)",
        "url": "str (Ghost URL, nullable)",
        "created_at": "ISO datetime string",
        "updated_at": "ISO datetime string",
    },
    "ContentPillar": {
        "id": "int (1-6, unique)",
        "name": "str",
        "weight": "float (normalized weights sum to 1.0)",
    },
}

RELATIONSHIPS = {
    "Signal-[BELONGS_TO]->ContentPillar": "Signal belongs to a pillar",
    "Signal-[CONTRIBUTES_TO]->Topic": "Signal contributed to topic formation",
    "Topic-[BELONGS_TO]->ContentPillar": "Topic belongs to a pillar",
    "Topic-[GENERATED]->Post": "Post was generated from topic",
    "Post-[BELONGS_TO]->ContentPillar": "Post belongs to a pillar",
    "Post-[FOLLOWS_UP]->Post": "Post is a follow-up to another post",
    "Topic-[TRACKED_BY]->OrbitTask": "Topic is tracked by an Orbit task (future)",
}
