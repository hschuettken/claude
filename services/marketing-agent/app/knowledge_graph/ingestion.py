"""Marketing KG ingestion service — syncs marketing entities to Neo4j.

Uses Neo4j async driver for graceful degradation. All ingestion is fire-and-forget:
failures are logged but never propagate.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton
from models import Signal, Topic, Draft

logger = logging.getLogger(__name__)


class MarketingKGIngestion:
    """Ingests marketing entities into the Neo4j Knowledge Graph.
    
    Provides high-level API for marketing entity ingestion with built-in
    error handling and KG availability checks.
    """

    def __init__(self, neo4j: Optional[Neo4jSingleton] = None):
        self.neo4j = neo4j or Neo4jSingleton()

    async def ingest_signal(self, signal: Signal) -> bool:
        """
        Ingest a Signal into the KG.

        Creates:
        - Signal node with properties
        - BELONGS_TO relationship to ContentPillar (if pillar_id set)

        Args:
            signal: Signal instance to ingest

        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            logger.debug(f"KG unavailable; skipping signal ingest for {signal.id}")
            return False

        try:
            signal_id = str(signal.id)
            
            # MERGE Signal node
            props = {
                "title": signal.title,
                "url": signal.url,
                "pillar_id": signal.pillar_id or 0,
                "relevance_score": signal.relevance_score,
                "detected_at": signal.detected_at.isoformat() if signal.detected_at else None,
                "status": signal.status,
                "created_at": signal.created_at.isoformat(),
            }
            await self._merge_node("Signal", signal_id, props)

            # Link Signal to ContentPillar (if pillar_id is set)
            if signal.pillar_id:
                await self._create_relationship(
                    from_label="Signal",
                    from_id=signal_id,
                    rel="BELONGS_TO",
                    to_label="ContentPillar",
                    to_id=str(signal.pillar_id),
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
            topic_id = str(topic.id)
            
            # MERGE Topic node
            props = {
                "title": topic.name,
                "summary": topic.pillar or "",
                "pillar_id": topic.pillar_id or 0,
                "score": float(topic.score) if topic.score else 0.0,
                "status": topic.status or "candidate",
                "created_at": topic.created_at.isoformat(),
            }
            await self._merge_node("Topic", topic_id, props)

            # Link Topic to ContentPillar
            if topic.pillar_id:
                await self._create_relationship(
                    from_label="Topic",
                    from_id=topic_id,
                    rel="BELONGS_TO",
                    to_label="ContentPillar",
                    to_id=str(topic.pillar_id),
                )

            # Link source signals to topic
            signal_ids = signal_ids or (getattr(topic, "signal_ids", None) or [])
            for sig_id in signal_ids:
                await self._create_relationship(
                    from_label="Signal",
                    from_id=str(sig_id),
                    rel="CONTRIBUTES_TO",
                    to_label="Topic",
                    to_id=topic_id,
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

        Args:
            draft: Draft instance to ingest as Post

        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            logger.debug(f"KG unavailable; skipping draft ingest for {draft.id}")
            return False

        try:
            post_id = str(draft.id)
            pillar_id = draft.topic.pillar_id if draft.topic else 0
            
            # MERGE Post node
            props = {
                "title": draft.title,
                "format": draft.platform.value if hasattr(draft.platform, 'value') else draft.platform or "blog",
                "pillar_id": pillar_id or 0,
                "word_count": len(draft.content.split()) if draft.content else 0,
                "status": draft.status.value if hasattr(draft.status, 'value') else draft.status or "draft",
                "published_at": draft.published_at.isoformat() if draft.published_at else None,
                "url": draft.ghost_url,
                "created_at": draft.created_at.isoformat(),
            }
            await self._merge_node("Post", post_id, props)

            # Link Post to ContentPillar
            if pillar_id:
                await self._create_relationship(
                    from_label="Post",
                    from_id=post_id,
                    rel="BELONGS_TO",
                    to_label="ContentPillar",
                    to_id=str(pillar_id),
                )

            # Link Post to Topic
            if draft.topic_id:
                await self._create_relationship(
                    from_label="Topic",
                    from_id=str(draft.topic_id),
                    rel="GENERATED",
                    to_label="Post",
                    to_id=post_id,
                )

            logger.info(f"✓ Ingested Post {post_id}: {draft.title[:40]}")
            return True

        except Exception as e:
            logger.error(f"Failed to ingest draft {draft.id}: {e}", exc_info=True)
            return False

    async def _merge_node(self, label: str, node_id: str, props: Dict) -> bool:
        """
        MERGE a node by id, SET all properties, with updated_at timestamp.
        
        Args:
            label: Node label (Signal, Topic, Post, etc.)
            node_id: Unique node ID
            props: Dictionary of properties to set
            
        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            return False

        try:
            cypher = f"""
            MERGE (n:{label} {{id: $id}})
            SET n += $props
            SET n.updated_at = datetime()
            RETURN n.id
            """
            await self.neo4j.execute(cypher, id=node_id, props=props)
            return True
        except Exception as e:
            logger.error(f"Failed to merge {label} node {node_id}: {e}")
            return False

    async def _create_relationship(
        self,
        from_label: str,
        from_id: str,
        rel: str,
        to_label: str,
        to_id: str,
    ) -> bool:
        """
        Create or merge a relationship between two nodes.
        
        Args:
            from_label: Source node label
            from_id: Source node ID
            rel: Relationship type (e.g., BELONGS_TO, CONTRIBUTES_TO)
            to_label: Target node label
            to_id: Target node ID
            
        Returns:
            True on success, False if KG unavailable or error.
        """
        if not self.neo4j.connected:
            return False

        try:
            # Sanitize rel_type to prevent Cypher injection (only allow uppercase/underscore)
            safe_rel = "".join(c for c in rel.upper() if c.isalpha() or c == "_")
            if not safe_rel:
                logger.warning(f"Invalid relationship type: {rel}")
                return False

            cypher = f"""
            MATCH (from:{from_label} {{id: $from_id}})
            MATCH (to:{to_label} {{id: $to_id}})
            MERGE (from)-[:{safe_rel}]->(to)
            RETURN count(*) as created
            """
            await self.neo4j.execute(cypher, from_id=from_id, to_id=to_id)
            return True
        except Exception as e:
            logger.error(
                f"Failed to create {safe_rel} relationship from {from_label}({from_id}) to {to_label}({to_id}): {e}"
            )
            return False
