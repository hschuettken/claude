"""Scout Engine status endpoints."""

from fastapi import APIRouter

from app.scout.scheduler import get_scheduler
from app.events.nats_client import NATSClient

router = APIRouter(prefix="/marketing/scout", tags=["scout"])


@router.get("/status", response_model=dict)
async def scout_status():
    """
    Get Scout Engine status.

    Returns:
    - running: Is scheduler currently running
    - searxng_initialized: Is SearXNG client initialized
    - jobs: List of scheduled jobs with next run times
    - last_runs: Info about last runs of each profile
    """
    scheduler = get_scheduler()
    return scheduler.get_status()


@router.get("/system/nats-status", response_model=dict)
async def nats_status():
    """
    Get NATS JetStream status.
    
    Returns:
    - connected: NATS connection status
    - server: NATS server URL (if connected)
    - available: Event bus availability
    """
    return {
        "connected": NATSClient.is_available(),
        "available": NATSClient.is_available(),
    }
