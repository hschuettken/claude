"""NATS consumers for marketing-agent.

Task 338: NATS-driven automation workflow
- Consume signal.high_relevance from NATS
- Trigger auto-draft generation in marketing-agent
- Notify for review

Schema: signal.high_relevance → detect → draft → notify cycle
"""

import asyncio
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from app.events.nats_client import NATSClient
from app.events.publishers import publish_draft_created

logger = logging.getLogger(__name__)


# Global task handle for graceful shutdown
_high_relevance_task = None


async def consume_high_relevance_signals():
    """
    NATS consumer: signal.high_relevance → detect → draft → notify cycle.
    
    For each high-relevance signal (score >= 0.8):
    1. Detect: Log signal detection
    2. Topic: Check if signal should trigger new topic + auto-draft
    3. Draft: Trigger auto-draft generation for high-score topic
    4. Notify: Publish notification for review
    
    Requires database access, so imports happen within function to avoid
    circular imports at module load time.
    """
    if not NATSClient.is_available():
        logger.info("NATS not available, high-relevance consumer not starting")
        return
    
    sub = await NATSClient.request_subscribe(
        "marketing.signals.detected",
        durable_name="hr-signal-processor"
    )
    
    if sub is None:
        logger.warning("Failed to subscribe to marketing.signals.detected")
        return
    
    logger.info("✅ High-relevance signal consumer started (Task 338: NATS automation)")
    
    try:
        async for msg in sub.messages:
            try:
                payload = json.loads(msg.data)
                score = payload.get("relevance_score", 0)
                
                if score >= 0.8:
                    # DETECT: Log high-relevance signal
                    signal_id = payload.get("signal_id")
                    title = payload.get("title", "Unknown")
                    logger.info(f"🔥 [DETECT] HIGH RELEVANCE signal: {signal_id} | {title} (score: {score})")
                    
                    # DRAFT + NOTIFY: Trigger auto-draft in background
                    asyncio.create_task(
                        _trigger_auto_draft_and_notify(signal_id, payload)
                    )
                
                await msg.ack()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse signal message: {e}")
                await msg.ack()  # Still ack to avoid infinite retry
            except Exception as e:
                logger.warning(f"Error processing signal message: {e}")
                await msg.ack()  # Still ack to avoid infinite retry
    except asyncio.CancelledError:
        logger.info("High-relevance consumer cancelled")
    except Exception as e:
        logger.error(f"High-relevance consumer error: {e}")


async def _trigger_auto_draft_and_notify(signal_id: int, signal_payload: dict):
    """
    Background task: trigger auto-draft generation and notify for review.
    
    This task:
    1. Checks if signal should trigger a topic + draft
    2. Creates the topic if needed
    3. Triggers draft generation
    4. Publishes notification event
    """
    try:
        # Import here to avoid circular imports at module load
        from database import SessionLocal
        from models import Topic, Signal, Draft
        from app.drafts.writer import DraftWriter
        
        db = SessionLocal()
        
        try:
            # Verify signal exists in database
            db_signal = db.query(Signal).filter(Signal.id == signal_id).first()
            if not db_signal:
                logger.warning(f"Signal {signal_id} not found in database")
                return
            
            # Check if we should create a topic and draft
            # Strategy: high-relevance signals (> 0.8) auto-trigger drafts
            # if no draft exists for this signal in last 14 days
            
            cutoff_14d = datetime.utcnow() - timedelta(days=14)
            
            # Check if signal already has a draft
            existing_drafts = (
                db.query(Draft)
                .join(Topic, Draft.topic_id == Topic.id)
                .filter(Topic.signal_ids.contains(f"[{signal_id}"))  # Basic check
                .filter(Draft.created_at >= cutoff_14d)
                .all()
            )
            
            if existing_drafts:
                logger.info(f"Draft already exists for signal {signal_id} within 14 days")
                return
            
            # Create a topic from the signal if needed
            topic = _ensure_topic_from_signal(db, db_signal)
            if not topic:
                logger.warning(f"Failed to create/find topic for signal {signal_id}")
                return
            
            logger.info(f"[DRAFT] Triggering auto-draft for topic {topic.id}: {topic.name}")
            
            # Generate draft
            draft_writer = DraftWriter(db)
            draft = await draft_writer.generate_blog_draft(topic.id)
            
            if draft:
                logger.info(f"[DRAFT] Auto-generated draft {draft.id} for topic {topic.id}")
                
                # Publish draft_created event for notification (Task 338: notify cycle)
                word_count = len((draft.content or "").split())
                await publish_draft_created(
                    draft_id=draft.id,
                    title=draft.title,
                    format="blog",
                    word_count=word_count,
                    generated_at=datetime.utcnow(),
                    pillar_id=topic.pillar_id if hasattr(topic, 'pillar_id') else None,
                )
                
                logger.info(f"[NOTIFY] Published draft created event for draft {draft.id} (Task 338)")
            else:
                logger.error(f"Failed to generate draft for topic {topic.id}")
        
        finally:
            db.close()
    
    except Exception as e:
        logger.error(f"Error in auto-draft trigger: {e}", exc_info=True)


def _ensure_topic_from_signal(db, signal) -> Optional:
    """
    Create or retrieve a topic from a high-relevance signal.
    
    Returns Topic or None.
    """
    from models import Topic
    
    try:
        # Check if topic already exists for this signal
        # (simplified: assume 1 signal = 1 topic for high-relevance)
        topic_name = f"Signal: {signal.title}"
        
        existing_topic = db.query(Topic).filter(Topic.name == topic_name).first()
        if existing_topic:
            logger.debug(f"Using existing topic {existing_topic.id}: {topic_name}")
            return existing_topic
        
        # Create new topic from signal
        topic = Topic(
            name=topic_name,
            pillar=f"pillar_{signal.pillar_id or 1}",
            audience_segment="general",
            created_at=datetime.utcnow(),
        )
        
        # Store extended fields if available
        if hasattr(topic, "score"):
            topic.score = signal.relevance_score
            topic.signal_ids = [signal.id]
            topic.pillar_id = signal.pillar_id or 1
            topic.status = "auto_draft"
        
        db.add(topic)
        db.flush()  # Get the ID
        db.commit()
        
        logger.info(f"Created topic {topic.id} from signal {signal.id}")
        return topic
    
    except Exception as e:
        logger.error(f"Error creating topic from signal: {e}")
        db.rollback()
        return None


async def start_consumers():
    """Start all NATS consumers."""
    global _high_relevance_task
    
    if not NATSClient.is_available():
        logger.info("NATS not available, consumers not starting")
        return
    
    # Start high-relevance signal consumer (Task 338) in background
    _high_relevance_task = asyncio.create_task(consume_high_relevance_signals())
    logger.info("NATS consumers initialized (including Task 338: high-relevance automation)")


async def close_consumers():
    """Stop all NATS consumers gracefully."""
    global _high_relevance_task
    
    if _high_relevance_task:
        _high_relevance_task.cancel()
        try:
            await _high_relevance_task
        except asyncio.CancelledError:
            logger.info("High-relevance consumer stopped")


__all__ = ["start_consumers", "close_consumers", "consume_high_relevance_signals"]
