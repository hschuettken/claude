"""
Marketing Agent Events Module

Re-exports NATS client and event publishers for easy importing.
"""

# Import and re-export the NATSClient for backward compatibility
from app.events.nats_client import NATSClient as MarketingNATSClient

__all__ = ["MarketingNATSClient"]
