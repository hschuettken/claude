"""Scout Engine status endpoints."""

from fastapi import APIRouter

from app.scout.scheduler import get_scheduler

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
