"""NATS event publishing for scout signals."""

import json
import logging
from datetime import datetime
from typing import Optional

import nats

logger = logging.getLogger(__name__)


class NATSPublisher:
    """Publishes scout events to NATS."""

    def __init__(self, nats_url: Optional[str] = None):
        self.nats_url = nats_url
        self.nc: Optional[nats.NATS] = None
        self.connected = False

    async def connect(self):
        """Connect to NATS server."""
        if not self.nats_url:
            logger.info("NATS_URL not set, event publishing disabled")
            return

        try:
            self.nc = await nats.connect(self.nats_url)
            self.connected = True
            logger.info(f"Connected to NATS at {self.nats_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to NATS at {self.nats_url}: {e}")
            self.connected = False

    async def disconnect(self):
        """Disconnect from NATS server."""
        if self.nc:
            try:
                await self.nc.close()
                logger.info("Disconnected from NATS")
            except Exception as e:
                logger.warning(f"Error closing NATS connection: {e}")
            finally:
                self.connected = False

    async def publish_signal_detected(
        self,
        signal_id: int,
        title: str,
        url: str,
        pillar_id: int,
        relevance_score: float,
        detected_at: datetime,
    ):
        """
        Publish a signal.detected event to NATS.

        Gracefully falls back if NATS is unavailable.
        """
        if not self.connected:
            logger.debug("NATS not connected, skipping publish")
            return

        payload = {
            "event": "signal.detected",
            "signal_id": signal_id,
            "title": title,
            "url": url,
            "pillar_id": pillar_id,
            "relevance_score": relevance_score,
            "detected_at": detected_at.isoformat(),
        }

        try:
            subject = "marketing.signals"
            message = json.dumps(payload).encode()
            await self.nc.publish(subject, message)
            logger.debug(f"Published signal.detected event: signal_id={signal_id}")
        except Exception as e:
            logger.warning(f"Failed to publish to NATS: {e}")


# Global NATS publisher instance
_nats_publisher: Optional[NATSPublisher] = None


def get_nats_publisher() -> NATSPublisher:
    """Get or create the global NATS publisher instance."""
    global _nats_publisher
    if _nats_publisher is None:
        _nats_publisher = NATSPublisher()
    return _nats_publisher


async def init_nats_publisher(nats_url: Optional[str] = None):
    """Initialize the NATS publisher."""
    global _nats_publisher
    _nats_publisher = NATSPublisher(nats_url)
    await _nats_publisher.connect()


async def close_nats_publisher():
    """Close the NATS publisher."""
    global _nats_publisher
    if _nats_publisher:
        await _nats_publisher.disconnect()
