"""KG auto-ingest hooks for marketing agent signals, topics, and drafts.

Hooks are called automatically from API endpoints when entities are created/updated.
Graceful degradation: logs and continues if KG unavailable.
"""

import asyncio
import logging
from typing import List, Optional

from app.knowledge_graph.ingestion import MarketingKGIngestion
from app.knowledge_graph.neo4j_singleton import Neo4jSingleton
from models import Signal, Topic, Draft

logger = logging.getLogger(__name__)


class KGHooks:
    """Async hooks for knowledge graph ingestion."""

    @staticmethod
    async def on_signal_created(signal: Signal) -> None:
        """
        Async hook called when a Signal is created.
        Ingests the signal into the KG.
        
        Args:
            signal: The newly created Signal object
        """
        try:
            neo4j = Neo4jSingleton()
            ingestion = MarketingKGIngestion(neo4j)
            success = await ingestion.ingest_signal(signal)
            if success:
                logger.info(f"KG: auto-ingested signal {signal.id} on creation")
            else:
                logger.debug(f"KG: skipped signal {signal.id} (unavailable)")
        except Exception as e:
            # Graceful degradation: log and continue
            logger.error(f"KG hook error on_signal_created({signal.id}): {e}", exc_info=True)

    @staticmethod
    async def on_signal_status_changed(signal: Signal, old_status: str, new_status: str) -> None:
        """
        Async hook called when Signal.status changes.
        If status → 'used', re-ingest the signal.
        
        Args:
            signal: The Signal object with updated status
            old_status: Previous status value
            new_status: New status value
        """
        try:
            if new_status == "used":
                neo4j = Neo4jSingleton()
                ingestion = MarketingKGIngestion(neo4j)
                success = await ingestion.ingest_signal(signal)
                if success:
                    logger.info(f"KG: auto-ingested signal {signal.id} (status: {old_status} → {new_status})")
                else:
                    logger.debug(f"KG: skipped signal {signal.id} status update (unavailable)")
        except Exception as e:
            # Graceful degradation: log and continue
            logger.error(
                f"KG hook error on_signal_status_changed({signal.id}, {old_status} → {new_status}): {e}",
                exc_info=True,
            )

    @staticmethod
    async def on_topic_created(topic: Topic, signal_ids: Optional[List[int]] = None) -> None:
        """
        Async hook called when a Topic is created.
        Ingests the topic into the KG with associated signal_ids.
        
        Args:
            topic: The newly created Topic object
            signal_ids: List of signal IDs that contributed to this topic (optional)
        """
        try:
            neo4j = Neo4jSingleton()
            ingestion = MarketingKGIngestion(neo4j)
            success = await ingestion.ingest_topic(topic, signal_ids=signal_ids)
            if success:
                logger.info(f"KG: auto-ingested topic {topic.id} with {len(signal_ids or [])} signals")
            else:
                logger.debug(f"KG: skipped topic {topic.id} (unavailable)")
        except Exception as e:
            # Graceful degradation: log and continue
            logger.error(f"KG hook error on_topic_created({topic.id}): {e}", exc_info=True)

    @staticmethod
    async def on_draft_status_changed(draft: Draft, old_status: str, new_status: str) -> None:
        """
        Async hook called when Draft.status changes.
        If status → 'approved' or 'published', ingest the draft as a Post.
        
        Args:
            draft: The Draft object with updated status
            old_status: Previous status value
            new_status: New status value
        """
        try:
            if new_status in ("approved", "published"):
                neo4j = Neo4jSingleton()
                ingestion = MarketingKGIngestion(neo4j)
                success = await ingestion.ingest_draft_as_post(draft)
                if success:
                    logger.info(f"KG: auto-ingested draft {draft.id} as Post (status: {old_status} → {new_status})")
                else:
                    logger.debug(f"KG: skipped draft {draft.id} status update (unavailable)")
        except Exception as e:
            # Graceful degradation: log and continue
            logger.error(
                f"KG hook error on_draft_status_changed({draft.id}, {old_status} → {new_status}): {e}",
                exc_info=True,
            )


def schedule_kg_hook(coro):
    """
    Wrapper to schedule an async hook as a background task.
    Useful when calling from sync context.
    
    Args:
        coro: Async coroutine to schedule
    
    Returns:
        Task handle (or None if event loop not available)
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context, just create task
            return asyncio.create_task(coro)
        else:
            # Sync context, run in new loop
            return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop, create new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
