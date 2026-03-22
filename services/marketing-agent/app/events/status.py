"""
NATS Status Endpoint for marketing-agent

Exposes /api/v1/system/nats-status endpoint showing event bus connectivity.
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
            "server": str,
            "last_check": str (ISO timestamp)
        }
    """
    return {
        "connected": NATSClient.is_available(),
        "available": NATSClient.is_available(),
        "server": "nats://192.168.0.90:4222",
        "last_check": datetime.utcnow().isoformat()
    }
