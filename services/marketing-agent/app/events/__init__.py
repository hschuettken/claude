"""Events module for marketing-agent."""

from .nats_client import NATSClient
from .publishers import (
    publish_signal_detected,
    publish_draft_created,
    publish_post_published,
    publish_performance_updated
)

__all__ = [
    "NATSClient",
    "publish_signal_detected",
    "publish_draft_created",
    "publish_post_published",
    "publish_performance_updated"
]
