"""
NATS Status Endpoint for marketing-agent

Exposes NATS event bus connectivity status.
"""

from datetime import datetime
from app.events.nats_client import NATSClient


async def get_nats_status() -> dict:
    """
    Get current NATS event bus status.
    
    Returns:
        {
            "connected": bool,
            "available": bool,
            "last_check": str (ISO timestamp)
        }
    """
    return {
        "connected": NATSClient.is_available(),
        "available": NATSClient.is_available(),
        "last_check": datetime.utcnow().isoformat()
    }
