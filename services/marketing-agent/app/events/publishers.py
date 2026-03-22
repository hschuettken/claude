"""
Marketing Agent Event Publishers

Publish marketing events to NATS JetStream:
- Signal detected (scout engine finds trending content)
- Draft created (LLM generates new topic draft)
- Post published (draft approved and published)
"""

import logging
from datetime import datetime
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


async def publish_signal_detected(
    signal_id: str,
    title: str,
    pillar_id: str,
    relevance_score: float,
    url: str,
    detected_at: datetime
) -> bool:
    """
    Publish when scout engine detects a signal (trending content).
    
    Subject: marketing.signals.detected
    """
    payload = {
        "signal_id": signal_id,
        "title": title,
        "pillar_id": pillar_id,
        "relevance_score": relevance_score,
        "url": url,
        "detected_at": detected_at.isoformat() if hasattr(detected_at, 'isoformat') else str(detected_at),
        "event_type": "signal.detected",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    success = await NATSClient.publish("marketing.signals.detected", payload)
    if success:
        logger.info(f"✅ Signal published: {signal_id} (score={relevance_score})")
    return success


async def publish_draft_created(
    draft_id: str,
    title: str,
    format: str,
    word_count: int,
    generated_at: datetime,
    pillar_id: Optional[str] = None
) -> bool:
    """
    Publish when LLM generates a new topic draft.
    
    Subject: marketing.drafts.created
    """
    payload = {
        "draft_id": draft_id,
        "topic_title": title,
        "format": format,
        "word_count": word_count,
        "pillar_id": pillar_id,
        "generated_at": generated_at.isoformat() if hasattr(generated_at, 'isoformat') else str(generated_at),
        "event_type": "draft.created",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    success = await NATSClient.publish("marketing.drafts.created", payload)
    if success:
        logger.info(f"✅ Draft published: {draft_id} ({word_count} words)")
    return success


async def publish_post_published(
    post_id: str,
    title: str,
    url: str,
    published_at: datetime,
    draft_id: Optional[str] = None
) -> bool:
    """
    Publish when a draft is approved and published.
    
    Subject: marketing.posts.published
    """
    payload = {
        "post_id": post_id,
        "title": title,
        "url": url,
        "draft_id": draft_id,
        "published_at": published_at.isoformat() if hasattr(published_at, 'isoformat') else str(published_at),
        "event_type": "post.published",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    success = await NATSClient.publish("marketing.posts.published", payload)
    if success:
        logger.info(f"✅ Post published: {post_id}")
    return success
