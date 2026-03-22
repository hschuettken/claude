"""NATS event publishing for scout signals."""

import logging
from datetime import datetime
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


async def on_signal_detected(
    signal_id: int,
    title: str,
    url: str,
    pillar_id: Optional[int],
    relevance_score: float,
    detected_at: Optional[datetime] = None,
):
    """
    Publish a signal.detected event to NATS.
    
    Called when a new signal is detected by scout.
    Gracefully falls back if NATS is unavailable.
    """
    if detected_at is None:
        detected_at = datetime.utcnow()
    
    payload = {
        "event": "signal.detected",
        "signal_id": signal_id,
        "title": title,
        "url": url,
        "pillar_id": pillar_id,
        "relevance_score": relevance_score,
        "detected_at": detected_at.isoformat(),
    }
    
    await NATSClient.publish("marketing.signals.detected", payload)
