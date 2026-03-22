"""Draft endpoints for marketing agent."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.drafts.writer import DraftWriter
from database import get_db
from models import Draft, Topic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing/drafts", tags=["drafts"])


class DraftCreate(BaseModel):
    """Request model for creating a draft."""

    topic_id: int = Field(..., description="Topic ID to generate draft from")
    format: str = Field(default="blog", description="blog, linkedin_teaser, linkedin_native")


class DraftUpdate(BaseModel):
    """Request model for updating a draft."""

    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    topic_id: Optional[int] = None
    platform: Optional[str] = None


class DraftResponse(BaseModel):
    """Response model for draft."""

    id: int
    title: str
    content: str
    status: str
    platform: str
    format: Optional[str] = None
    topic_id: Optional[int] = None
    word_count: Optional[int] = None
    outline: Optional[dict] = None
    seo_meta: Optional[dict] = None
    risk_flags: Optional[List[dict]] = None
    confidence_labels: Optional[dict] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[DraftResponse])
async def list_drafts(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    format: Optional[str] = None,
    topic_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List drafts with optional filtering."""
    query = db.query(Draft)

    if status:
        query = query.filter(Draft.status == status)

    if format and hasattr(Draft, 'format'):
        query = query.filter(Draft.format == format)

    if topic_id:
        query = query.filter(Draft.topic_id == topic_id)

    drafts = query.order_by(Draft.created_at.desc()).offset(offset).limit(limit).all()
    return drafts


@router.post("", response_model=dict, status_code=202)
async def create_draft(
    draft_req: DraftCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a new blog draft from topic (async, background task).
    
    Returns immediately with status 202 (accepted).
    """
    # Verify topic exists
    topic = db.query(Topic).filter(Topic.id == draft_req.topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Start draft generation in background
    writer = DraftWriter(db)
    background_tasks.add_task(writer.generate_blog_draft, draft_req.topic_id)

    return {
        "status": "generating",
        "topic_id": draft_req.topic_id,
        "message": "Blog draft generation started in background"
    }


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: int, db: Session = Depends(get_db)):
    """Get a specific draft by ID."""
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.patch("/{draft_id}", response_model=DraftResponse)
async def update_draft(draft_id: int, draft_update: DraftUpdate, db: Session = Depends(get_db)):
    """Update a draft (status, content, title)."""
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Update only provided fields
    if draft_update.title is not None:
        draft.title = draft_update.title
    if draft_update.content is not None:
        draft.content = draft_update.content
    if draft_update.status is not None:
        draft.status = draft_update.status
    if draft_update.topic_id is not None:
        draft.topic_id = draft_update.topic_id
    if draft_update.platform is not None:
        draft.platform = draft_update.platform

    db.commit()
    db.refresh(draft)
    return draft


@router.post("/{draft_id}/linkedin", response_model=dict, status_code=202)
async def generate_linkedin_variants(
    draft_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Generate LinkedIn teaser and native posts from blog draft.
    
    Returns immediately with status 202 (accepted).
    """
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    writer = DraftWriter(db)
    background_tasks.add_task(writer.generate_linkedin_teaser, draft_id)
    background_tasks.add_task(writer.generate_linkedin_native, draft_id)

    return {
        "status": "generating",
        "draft_id": draft_id,
        "message": "LinkedIn variants generation started in background"
    }


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    """Delete a draft (soft delete: set status to rejected)."""
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Soft delete: set status to rejected
    draft.status = "rejected"
    db.commit()
    return None
