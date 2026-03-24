"""Knowledge Graph status and health check API."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.knowledge_graph import (
    get_kg_status,
    get_cached_kg_status,
    initialize_kg,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/marketing/kg", tags=["knowledge-graph"])


class NodeCount(BaseModel):
    """Node type and count."""
    label: str
    count: int


class PillarStats(BaseModel):
    """Content pillar statistics."""
    id: int
    name: str
    post_count: int
    published_count: int
    last_published: str = None


class KGStatusResponse(BaseModel):
    """Knowledge Graph status response."""
    connected: bool
    error: str = None
    node_counts: Dict[str, int] = {}
    pillars: Dict[str, Any] = {}


@router.get("/status", response_model=KGStatusResponse)
async def get_kg_status_endpoint() -> KGStatusResponse:
    """
    Get current Knowledge Graph status.
    
    Returns:
      - connected: True if Neo4j is reachable
      - node_counts: Dict of label -> count for all node types
      - pillars: Statistics for each content pillar
      - error: Error message if not connected
    """
    status = await get_kg_status()
    return KGStatusResponse(**status)


@router.post("/initialize")
async def initialize_kg_endpoint() -> Dict[str, Any]:
    """
    Initialize the Knowledge Graph schema and seed data.
    
    This is idempotent—safe to call multiple times.
    Creates:
    - Constraints for Signal, Topic, Post, ContentPillar nodes
    - Indexes for efficient querying
    - 6 ContentPillar seed nodes
    
    Returns:
      - success: True if initialization succeeded
      - connected: True if Neo4j connection established
      - constraints_created: Number of constraints created
      - pillars_seeded: Number of pillar nodes seeded
      - error: Error message if any
    """
    logger.info("KG initialization requested via API")
    result = await initialize_kg()
    
    if result["success"]:
        logger.info("✓ KG initialization complete")
    else:
        logger.error(f"KG initialization failed: {result.get('error')}")
    
    return result


@router.get("/pillars", response_model=Dict[int, PillarStats])
async def get_pillars_stats() -> Dict[int, PillarStats]:
    """
    Get statistics for all 6 content pillars.
    
    Returns:
      - pillar_id: (name, post_count, published_count, last_published)
    
    Example:
      {
        "1": {"name": "SAP deep technical", "post_count": 5, "published_count": 3, ...},
        "2": {"name": "SAP roadmap & features", "post_count": 2, "published_count": 1, ...},
        ...
      }
    """
    status = await get_kg_status()
    if not status.get("connected"):
        return {}
    
    pillars = status.get("pillars", {})
    return pillars


@router.get("/health")
async def kg_health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring.
    
    Returns 200 if KG is connected, 503 otherwise.
    """
    cached = get_cached_kg_status()
    if cached and cached.get("connected"):
        return {"status": "healthy", "connected": True}
    
    status = await get_kg_status()
    if status.get("connected"):
        return {"status": "healthy", "connected": True}
    
    return {
        "status": "unavailable",
        "connected": False,
        "error": status.get("error", "Unknown error"),
    }, 503
