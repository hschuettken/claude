"""Signal endpoints for marketing agent."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Signal

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalCreate(BaseModel):
    """Request model for creating a signal."""

    title: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)
    source: str = Field(..., min_length=1, max_length=128)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    kg_node_id: Optional[str] = Field(None, max_length=128)


class SignalResponse(BaseModel):
    """Response model for signal."""

    id: int
    title: str
    url: str
    source: str
    relevance_score: float
    kg_node_id: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[SignalResponse])
async def list_signals(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: Optional[str] = None,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """List signals with optional filtering."""
    query = db.query(Signal)

    if source:
        query = query.filter(Signal.source == source)

    if min_score > 0:
        query = query.filter(Signal.relevance_score >= min_score)

    signals = query.order_by(Signal.created_at.desc()).offset(offset).limit(limit).all()
    return signals


@router.post("", response_model=SignalResponse, status_code=201)
async def create_signal(signal: SignalCreate, db: Session = Depends(get_db)):
    """Create a new signal."""
    db_signal = Signal(
        title=signal.title,
        url=signal.url,
        source=signal.source,
        relevance_score=signal.relevance_score,
        kg_node_id=signal.kg_node_id,
    )
    db.add(db_signal)
    db.commit()
    db.refresh(db_signal)
    return db_signal


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int, db: Session = Depends(get_db)):
    """Get a specific signal by ID."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.delete("/{signal_id}", status_code=204)
async def delete_signal(signal_id: int, db: Session = Depends(get_db)):
    """Delete a signal by ID."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    db.delete(signal)
    db.commit()
    return None
