"""NATS event publishing for drafts."""

import logging
from datetime import datetime
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


async def on_draft_created(
    draft_id: int,
    title: str,
    topic_id: Optional[int],
    format: str,
    word_count: int,
    created_at: Optional[datetime] = None,
):
    """
    Publish a draft.created event to NATS.
    
    Called when a new draft is created.
    Gracefully falls back if NATS is unavailable.
    """
    if created_at is None:
        created_at = datetime.utcnow()
    
    payload = {
        "event": "draft.created",
        "draft_id": draft_id,
        "title": title,
        "topic_id": topic_id,
        "format": format,
        "word_count": word_count,
        "created_at": created_at.isoformat(),
    }
    
    await NATSClient.publish("marketing.drafts.created", payload)
