"""Signal endpoints for marketing agent."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.scout.scheduler import get_scheduler
from database import get_db
from models import Signal

router = APIRouter(prefix="/marketing/signals", tags=["signals"])


class SignalCreate(BaseModel):
    """Request model for creating a signal."""

    title: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)
    source: str = Field(..., min_length=1, max_length=128)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    kg_node_id: Optional[str] = Field(None, max_length=128)


class SignalUpdate(BaseModel):
    """Request model for updating a signal."""

    status: Optional[str] = Field(None, pattern="^(new|read|used|archived)$")


class SignalResponse(BaseModel):
    """Response model for signal."""

    id: int
    title: str
    url: str
    source: str
    source_domain: Optional[str]
    snippet: Optional[str]
    relevance_score: float
    pillar_id: Optional[int]
    search_profile_id: Optional[str]
    status: str
    detected_at: Optional[datetime]
    created_at: datetime
    kg_node_id: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=List[SignalResponse])
async def list_signals(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pillar_id: Optional[int] = None,
    status: Optional[str] = None,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    source: Optional[str] = None,
    since: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    """
    List signals with pagination and filtering.

    Query params:
    - limit: Max results (default 50, max 500)
    - offset: Skip N results (default 0)
    - pillar_id: Filter by content pillar (1-6)
    - status: Filter by status (new, read, used, archived)
    - min_score: Minimum relevance score (0.0-1.0)
    - source: Filter by source/engine
    - since: Filter by detected_at >= timestamp
    """
    query = db.query(Signal)

    if pillar_id is not None:
        query = query.filter(Signal.pillar_id == pillar_id)

    if status:
        query = query.filter(Signal.status == status)

    if min_score > 0:
        query = query.filter(Signal.relevance_score >= min_score)

    if source:
        query = query.filter(Signal.source == source)

    if since:
        query = query.filter(Signal.detected_at >= since)

    signals = query.order_by(Signal.detected_at.desc()).offset(offset).limit(limit).all()
    return signals


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int, db: Session = Depends(get_db)):
    """Get a specific signal by ID."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.patch("/{signal_id}", response_model=SignalResponse)
async def update_signal(signal_id: int, update: SignalUpdate, db: Session = Depends(get_db)):
    """Update a signal (e.g., status change)."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    if update.status:
        signal.status = update.status

    db.commit()
    db.refresh(signal)
    return signal


@router.post("/refresh", response_model=dict)
async def trigger_refresh():
    """
    Trigger an immediate scan of all search profiles.

    Returns job_id and number of profiles queued.
    """
    scheduler = get_scheduler()
    if not scheduler.is_running:
        raise HTTPException(status_code=503, detail="Scout scheduler not running")

    result = await scheduler.trigger_refresh()
    return result
