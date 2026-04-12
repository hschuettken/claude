"""NATS event publishing for scout signals."""

import logging
from datetime import datetime
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


class NATSPublisher:
    """Publisher for scout signal events via NATS JetStream."""

    def __init__(self):
        self._nats_available = False

    async def initialize(self, nats_url: Optional[str]):
        """Initialize NATS connection."""
        if not nats_url:
            logger.info("NATS_URL not configured — NATS event publishing disabled")
            self._nats_available = False
        else:
            connected = await NATSClient.connect(nats_url, user="", password="")
            self._nats_available = connected

    async def publish_signal_detected(
        self,
        signal_id: int,
        title: str,
        url: str,
        pillar_id: Optional[int],
        relevance_score: float,
        detected_at: Optional[datetime] = None,
    ) -> bool:
        """
        Publish a signal.detected event to NATS.

        Called when a new signal is detected by scout.
        Gracefully skips if NATS is unavailable.

        Returns True if published successfully, False if unavailable.
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

        if not self._nats_available:
            logger.debug("nats_publish_skipped_not_available signal=%d", signal_id)
            return False

        try:
            success = await NATSClient.publish("marketing.signals.detected", payload)
            if success:
                logger.debug("Published to NATS: signal %d", signal_id)
            return success
        except Exception as e:
            logger.warning("Failed to publish to NATS: %s", e)
            return False

    async def close(self):
        """Close NATS connection."""
        await NATSClient.close()

    def is_available(self) -> bool:
        """Check if NATS event bus is available."""
        return self._nats_available and NATSClient.is_available()


# Global publisher instance
_publisher: Optional[NATSPublisher] = None


async def init_nats_publisher(nats_url: Optional[str]):
    """Initialize global NATS publisher."""
    global _publisher
    _publisher = NATSPublisher()
    await _publisher.initialize(nats_url)


def get_nats_publisher() -> NATSPublisher:
    """Get global NATS publisher."""
    global _publisher
    if _publisher is None:
        _publisher = NATSPublisher()
    return _publisher


async def close_nats_publisher():
    """Close global NATS publisher."""
    global _publisher
    if _publisher:
        await _publisher.close()
        _publisher = None


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
    publisher = get_nats_publisher()
    await publisher.publish_signal_detected(
        signal_id, title, url, pillar_id, relevance_score, detected_at
    )
