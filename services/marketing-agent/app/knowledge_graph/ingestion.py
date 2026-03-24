"""Marketing KG ingestion service — syncs marketing entities to Neo4j."""

import logging
from datetime import datetime
from typing import List, Optional

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton
from models import Signal, Topic, Draft

logger = logging.getLogger(__name__)


class MarketingKGIngestion:
    """Ingests marketing entities into the Neo4j Knowledge Graph."""

    def __init__(self, neo4j: Optional[Neo4jSingleton] = None):
        self.neo4j = neo4j or Neo4jSingleton()

    async def ingest_signal(self, signal: Signal) -> bool:
        """
        Ingest a Signal into the KG.

        Creates:
        - Signal node with properties
        - BELONGS_TO relationship to ContentPillar (if pillar_id set)

        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            logger.debug(f"KG unavailable; skipping signal ingest for {signal.id}")
            return False

        try:
            # MERGE Signal node
            cypher_signal = """
            MERGE (s:Signal {id: $signal_id})
            SET s.title = $title,
                s.url = $url,
                s.pillar_id = $pillar_id,
                s.relevance_score = $relevance_score,
                s.detected_at = $detected_at,
                s.status = $status,
                s.created_at = $created_at,
                s.updated_at = datetime()
            RETURN s.id
            """

            signal_id = str(signal.id)
            await self.neo4j.execute(
                cypher_signal,
                signal_id=signal_id,
                title=signal.title,
                url=signal.url,
                pillar_id=signal.pillar_id or 0,
                relevance_score=signal.relevance_score,
                detected_at=signal.detected_at.isoformat() if signal.detected_at else None,
                status=signal.status,
                created_at=signal.created_at.isoformat(),
            )

            # Link Signal to ContentPillar (if pillar_id is set)
            if signal.pillar_id:
                cypher_pillar = """
                MATCH (s:Signal {id: $signal_id})
                MATCH (cp:ContentPillar {id: $pillar_id})
                MERGE (s)-[:BELONGS_TO]->(cp)
                RETURN cp.id
                """
                await self.neo4j.execute(
                    cypher_pillar,
                    signal_id=signal_id,
                    pillar_id=signal.pillar_id,
                )

            logger.info(f"✓ Ingested Signal {signal_id}: {signal.title[:40]}")
            return True

        except Exception as e:
            logger.error(f"Failed to ingest signal {signal.id}: {e}", exc_info=True)
            return False

    async def ingest_topic(self, topic: Topic, signal_ids: Optional[List[int]] = None) -> bool:
        """
        Ingest a Topic into the KG.

        Creates:
        - Topic node with properties
        - BELONGS_TO relationship to ContentPillar
        - CONTRIBUTES_TO relationships from source signals

        Args:
            topic: Topic to ingest
            signal_ids: List of signal IDs that contributed to this topic

        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            logger.debug(f"KG unavailable; skipping topic ingest for {topic.id}")
            return False

        try:
            # MERGE Topic node
            cypher_topic = """
            MERGE (t:Topic {id: $topic_id})
            SET t.title = $title,
                t.summary = $summary,
                t.pillar_id = $pillar_id,
                t.score = $score,
                t.status = $status,
                t.created_at = $created_at,
                t.updated_at = datetime()
            RETURN t.id
            """

            topic_id = str(topic.id)
            await self.neo4j.execute(
                cypher_topic,
                topic_id=topic_id,
                title=topic.name,
                summary=topic.pillar or "",
                pillar_id=topic.pillar_id or 0,
                score=float(topic.score) if topic.score else 0.0,
                status=topic.status or "candidate",
                created_at=topic.created_at.isoformat(),
            )

            # Link Topic to ContentPillar
            if topic.pillar_id:
                cypher_pillar = """
                MATCH (t:Topic {id: $topic_id})
                MATCH (cp:ContentPillar {id: $pillar_id})
                MERGE (t)-[:BELONGS_TO]->(cp)
                RETURN cp.id
                """
                await self.neo4j.execute(
                    cypher_pillar,
                    topic_id=topic_id,
                    pillar_id=topic.pillar_id,
                )

            # Link source signals to topic
            signal_ids = signal_ids or topic.signal_ids or []
            for sig_id in signal_ids:
                cypher_signal = """
                MATCH (s:Signal {id: $signal_id})
                MATCH (t:Topic {id: $topic_id})
                MERGE (s)-[:CONTRIBUTES_TO]->(t)
                RETURN t.id
                """
                await self.neo4j.execute(
                    cypher_signal,
                    signal_id=str(sig_id),
                    topic_id=topic_id,
                )

            logger.info(f"✓ Ingested Topic {topic_id}: {topic.name[:40]}")
            return True

        except Exception as e:
            logger.error(f"Failed to ingest topic {topic.id}: {e}", exc_info=True)
            return False

    async def ingest_draft_as_post(self, draft: Draft) -> bool:
        """
        Ingest a Draft as a Post into the KG.

        Creates:
        - Post node with properties
        - BELONGS_TO relationship to ContentPillar
        - GENERATED relationship from Topic

        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            logger.debug(f"KG unavailable; skipping draft ingest for {draft.id}")
            return False

        try:
            # MERGE Post node
            cypher_post = """
            MERGE (p:Post {id: $post_id})
            SET p.title = $title,
                p.format = $format,
                p.pillar_id = $pillar_id,
                p.word_count = $word_count,
                p.status = $status,
                p.published_at = $published_at,
                p.created_at = $created_at,
                p.updated_at = datetime()
            RETURN p.id
            """

            post_id = str(draft.id)
            pillar_id = draft.topic.pillar_id if draft.topic else 0
            await self.neo4j.execute(
                cypher_post,
                post_id=post_id,
                title=draft.title,
                format=draft.format or "blog",
                pillar_id=pillar_id or 0,
                word_count=draft.word_count or 0,
                status=draft.status,
                published_at=None,  # Set when post is actually published
                created_at=draft.created_at.isoformat(),
            )

            # Link Post to ContentPillar
            if pillar_id:
                cypher_pillar = """
                MATCH (p:Post {id: $post_id})
                MATCH (cp:ContentPillar {id: $pillar_id})
                MERGE (p)-[:BELONGS_TO]->(cp)
                RETURN cp.id
                """
                await self.neo4j.execute(
                    cypher_pillar,
                    post_id=post_id,
                    pillar_id=pillar_id,
                )

            # Link Post to Topic
            if draft.topic_id:
                cypher_topic = """
                MATCH (t:Topic {id: $topic_id})
                MATCH (p:Post {id: $post_id})
                MERGE (t)-[:GENERATED]->(p)
                RETURN p.id
                """
                await self.neo4j.execute(
                    cypher_topic,
                    topic_id=str(draft.topic_id),
                    post_id=post_id,
                )

            logger.info(f"✓ Ingested Post {post_id}: {draft.title[:40]}")
            return True

        except Exception as e:
            logger.error(f"Failed to ingest draft {draft.id}: {e}", exc_info=True)
            return False
