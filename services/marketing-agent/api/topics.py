"""Topic endpoints for marketing agent."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.topics.service import TopicService
from database import get_db
from models import Topic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing/topics", tags=["topics"])


class TopicCreate(BaseModel):
    """Request model for creating a topic."""

    name: str = Field(..., min_length=1, max_length=255)
    pillar: str = Field(..., min_length=1, max_length=255)
    audience_segment: str = Field(..., min_length=1, max_length=255)


class TopicUpdate(BaseModel):
    """Request model for updating a topic."""

    status: Optional[str] = None


class TopicResponse(BaseModel):
    """Response model for topic."""

    id: int
    name: str
    pillar: str
    audience_segment: str
    score: Optional[float] = None
    score_breakdown: Optional[dict] = None
    status: Optional[str] = None
    signal_ids: Optional[List[int]] = None
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[TopicResponse])
async def list_topics(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    pillar_id: Optional[int] = None,
    min_score: Optional[float] = None,
    audience: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List topics with optional filtering."""
    service = TopicService(db)
    
    query = db.query(Topic)

    if status:
        query = query.filter(Topic.status == status)
    
    if pillar:
        query = query.filter(Topic.pillar == pillar)
    
    if pillar_id:
        query = query.filter(Topic.pillar_id == pillar_id)

    if min_score is not None:
        query = query.filter(Topic.score >= min_score)

    if audience:
        query = query.filter(Topic.audience_segment == audience)

    total = query.count()
    topics = query.order_by(Topic.score.desc() if hasattr(Topic, 'score') else Topic.created_at.desc()).offset(offset).limit(limit).all()
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


@router.get("/top", response_model=List[TopicResponse])
async def get_top_topics(
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Get top topics by score (weekly content proposal)."""
    service = TopicService(db)
    topics = service.get_top_topics(limit=limit)
    return topics


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: int, db: Session = Depends(get_db)):
    """Get a specific topic by ID."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.patch("/{topic_id}", response_model=TopicResponse)
async def update_topic(topic_id: int, update: TopicUpdate, db: Session = Depends(get_db)):
    """Update topic (e.g., status)."""
    service = TopicService(db)
    topic = service.update_topic_status(topic_id, update.status)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


async def _run_refresh_and_auto_draft(days: int, min_score: float, db: Session) -> None:
    """Background: cluster topics then dispatch draft generation for high-score ones."""
    from app.drafts.writer import DraftWriter

    service = TopicService(db)
    await service.refresh_topics(days, min_score)
    auto_ids = service.pop_auto_draft_ids()
    if auto_ids:
        writer = DraftWriter(db)
        for topic_id in auto_ids:
            try:
                await writer.generate_blog_draft(topic_id)
            except Exception as e:
                logger.error(f"Auto-draft failed for topic {topic_id}: {e}")


@router.post("/refresh", status_code=202)
async def refresh_topics(
    days: int = Query(7, ge=1, le=30),
    min_score: float = Query(0.4, ge=0.0, le=1.0),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Refresh topics from recent signals; auto-draft any topic scoring > 0.8."""
    if background_tasks:
        background_tasks.add_task(_run_refresh_and_auto_draft, days, min_score, db)
    else:
        import asyncio
        asyncio.run(_run_refresh_and_auto_draft(days, min_score, db))

    return {"status": "refreshing", "message": "Topic refresh + auto-draft started in background"}
