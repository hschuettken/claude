"""Scout Engine status endpoints."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Header, BackgroundTasks

from app.scout.scheduler import get_scheduler, load_profiles, run_scout_profile
try:
    from app.events.nats_client import NATSClient
except ImportError:
    from events import MarketingNATSClient as NATSClient
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketing/scout", tags=["scout"])


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """
    Verify API key from X-API-Key header.
    
    Returns:
        The API key if valid
        
    Raises:
        HTTPException 401 if key is missing or invalid
    """
    import os
    
    expected_key = os.getenv("MARKETING_API_KEY")
    if not expected_key:
        logger.warning("MARKETING_API_KEY not configured, skipping auth")
        return ""
    
    if not x_api_key or x_api_key != expected_key:
        logger.warning(f"Invalid or missing API key in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )
    
    return x_api_key


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


@router.post("/run/{profile_id}", response_model=dict)
async def run_profile(
    profile_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """
    Manually trigger a scout profile scan.
    
    Args:
        profile_id: Profile ID to run (e.g., "sap_datasphere")
        
    Returns:
        - status: "ok" or error status
        - profile_id: The profile that was triggered
        - triggered_at: ISO timestamp when trigger was issued
        
    Raises:
        401: If API key is missing or invalid
        404: If profile_id not found
        500: On unexpected server errors
    """
    try:
        # Load all profiles
        profiles = load_profiles()
        
        if not profiles:
            logger.error("No profiles configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No profiles configured"
            )
        
        # Find the requested profile
        profile = next((p for p in profiles if p.id == profile_id), None)
        
        if not profile:
            logger.warning(f"Profile '{profile_id}' not found in {len(profiles)} profiles")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile '{profile_id}' not found"
            )
        
        # Queue the profile run in background
        logger.info(f"Triggering profile '{profile_id}' on demand")
        background_tasks.add_task(run_scout_profile, profile, db)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "triggered_at": datetime.utcnow().isoformat(),
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions (400, 401, 404, etc)
        raise
    except Exception as e:
        logger.exception(f"Unexpected error running profile '{profile_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger profile: {str(e)}"
        )
