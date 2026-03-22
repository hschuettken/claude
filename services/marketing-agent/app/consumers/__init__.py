"""NATS consumers for marketing-agent."""

import asyncio
import json
import logging
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


async def consume_high_relevance_signals():
    """
    Subscribe to marketing.signals.detected and process high-relevance signals.
    
    If score > 0.8:
      - Log "HIGH RELEVANCE signal detected: {title}"
      - Update signal status to "highlighted"
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
    
    logger.info("✅ High-relevance signal consumer started")
    
    try:
        async for msg in sub.messages:
            try:
                payload = json.loads(msg.data)
                score = payload.get("relevance_score", 0)
                
                if score >= 0.8:
                    title = payload.get("title", "Unknown")
                    logger.info(f"🔥 HIGH RELEVANCE signal detected: {title} (score: {score})")
                    
                    # Future: update signal status in database
                    # await update_signal_status(payload["signal_id"], "highlighted")
                
                await msg.ack()
            except Exception as e:
                logger.warning(f"Error processing signal message: {e}")
                await msg.ack()  # Still ack to avoid infinite retry
    except Exception as e:
        logger.error(f"High-relevance consumer error: {e}")


async def start_consumers():
    """Start all NATS consumers."""
    if not NATSClient.is_available():
        logger.info("NATS not available, consumers not starting")
        return
    
    # Start high-relevance signal consumer in background
    asyncio.create_task(consume_high_relevance_signals())
    logger.info("NATS consumers initialized")


__all__ = ["start_consumers", "consume_high_relevance_signals"]
