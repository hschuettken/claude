"""Topic endpoints for marketing agent."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Topic

router = APIRouter(prefix="/topics", tags=["topics"])


class TopicCreate(BaseModel):
    """Request model for creating a topic."""

    name: str = Field(..., min_length=1, max_length=255)
    pillar: str = Field(..., min_length=1, max_length=255)
    audience_segment: str = Field(..., min_length=1, max_length=255)


class TopicResponse(BaseModel):
    """Response model for topic."""

    id: int
    name: str
    pillar: str
    audience_segment: str
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[TopicResponse])
async def list_topics(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pillar: Optional[str] = None,
    audience: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List topics with optional filtering."""
    query = db.query(Topic)

    if pillar:
        query = query.filter(Topic.pillar == pillar)

    if audience:
        query = query.filter(Topic.audience_segment == audience)

    topics = query.order_by(Topic.created_at.desc()).offset(offset).limit(limit).all()
    return topics


@router.post("", response_model=TopicResponse, status_code=201)
async def create_topic(topic: TopicCreate, db: Session = Depends(get_db)):
    """Create a new topic."""
    # Check for duplicate name
    existing = db.query(Topic).filter(Topic.name == topic.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Topic with this name already exists")

    db_topic = Topic(
        name=topic.name,
        pillar=topic.pillar,
        audience_segment=topic.audience_segment,
    )
    db.add(db_topic)
    db.commit()
    db.refresh(db_topic)
    return db_topic


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: int, db: Session = Depends(get_db)):
    """Get a specific topic by ID."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
