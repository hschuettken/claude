"""Content topics and pillars API."""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..models import Topic
from ..kg_ingest import get_kg_ingest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/topics", tags=["topics"])


class TopicCreate(BaseModel):
    """Create topic request."""
    name: str
    pillar: str
    audience_segment: Optional[str] = None


class TopicUpdate(BaseModel):
    """Update topic request."""
    name: Optional[str] = None
    pillar: Optional[str] = None
    audience_segment: Optional[str] = None


class TopicResponse(BaseModel):
    """Topic response."""
    id: int
    name: str
    pillar: str
    audience_segment: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True


@router.post("", response_model=TopicResponse)
async def create_topic(
    topic: TopicCreate,
    db: AsyncSession,
) -> TopicResponse:
    """Create a new content topic.
    
    Automatically ingests to Knowledge Graph if available.
    """
    new_topic = Topic(
        name=topic.name,
        pillar=topic.pillar,
        audience_segment=topic.audience_segment,
    )
    
    db.add(new_topic)
    await db.flush()
    
    # Ingest to Knowledge Graph
    kg_ingest = get_kg_ingest()
    await kg_ingest.ingest_topic(
        topic_id=new_topic.id,
        title=new_topic.name,
        summary=None,
        pillar_id=None,  # Can be mapped from topic.pillar if needed
        score=0.5,  # Default score
        signal_ids=[],  # Can be populated later
    )
    
    logger.info(f"Topic created: {new_topic.id} ({topic.name})")
    return TopicResponse.model_validate(new_topic)


@router.get("", response_model=List[TopicResponse])
async def list_topics(
    db: AsyncSession,
) -> List[TopicResponse]:
    """List all content topics."""
    query = select(Topic).order_by(Topic.name)
    result = await db.execute(query)
    topics = result.scalars().all()
    
    return [TopicResponse.model_validate(t) for t in topics]


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: int,
    db: AsyncSession,
) -> TopicResponse:
    """Get a single topic by ID."""
    query = select(Topic).where(Topic.id == topic_id)
    result = await db.execute(query)
    topic = result.scalar_one_or_none()
    
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    
    return TopicResponse.model_validate(topic)


@router.put("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: int,
    update: TopicUpdate,
    db: AsyncSession,
) -> TopicResponse:
    """Update a topic."""
    query = select(Topic).where(Topic.id == topic_id)
    result = await db.execute(query)
    topic = result.scalar_one_or_none()
    
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(topic, key, value)
    
    await db.flush()
    logger.info(f"Topic updated: {topic_id}")
    
    return TopicResponse.model_validate(topic)
