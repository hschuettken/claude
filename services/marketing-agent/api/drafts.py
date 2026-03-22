"""Draft endpoints for marketing agent."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Draft

router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftCreate(BaseModel):
    """Request model for creating a draft."""

    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(...)
    platform: str = Field(..., min_length=1, max_length=64)
    status: str = Field(default="draft")
    topic_id: Optional[int] = None


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
    topic_id: Optional[int]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[DraftResponse])
async def list_drafts(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    platform: Optional[str] = None,
    topic_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List drafts with optional filtering."""
    query = db.query(Draft)

    if status:
        query = query.filter(Draft.status == status)

    if platform:
        query = query.filter(Draft.platform == platform)

    if topic_id:
        query = query.filter(Draft.topic_id == topic_id)

    drafts = query.order_by(Draft.created_at.desc()).offset(offset).limit(limit).all()
    return drafts


@router.post("", response_model=DraftResponse, status_code=201)
async def create_draft(draft: DraftCreate, db: Session = Depends(get_db)):
    """Create a new draft."""
    db_draft = Draft(
        title=draft.title,
        content=draft.content,
        platform=draft.platform,
        status=draft.status,
        topic_id=draft.topic_id,
    )
    db.add(db_draft)
    db.commit()
    db.refresh(db_draft)
    return db_draft


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: int, db: Session = Depends(get_db)):
    """Get a specific draft by ID."""
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.put("/{draft_id}", response_model=DraftResponse)
async def update_draft(draft_id: int, draft_update: DraftUpdate, db: Session = Depends(get_db)):
    """Update a draft."""
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


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    """Delete a draft."""
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    db.delete(draft)
    db.commit()
    return None
