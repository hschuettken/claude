"""Marketing signals API — detect and register marketing opportunities."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from pydantic import BaseModel

from ..models import Signal, SignalStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["signals"])


class SignalCreate(BaseModel):
    """Create signal request."""
    title: str
    url: Optional[str] = None
    source: str  # scout, manual, research, etc.
    relevance_score: float = 0.5  # 0.0-1.0
    kg_node_id: Optional[str] = None


class SignalStatusUpdate(BaseModel):
    """Update signal status."""
    status: str  # new, read, used, archived


class SignalResponse(BaseModel):
    """Signal response."""
    id: int
    title: str
    url: Optional[str]
    snippet: Optional[str]
    source: str
    source_domain: Optional[str]
    relevance_score: float
    pillar_id: Optional[int]
    status: str
    kg_node_id: Optional[str]
    url_hash: Optional[str]
    search_profile_id: Optional[str]
    detected_at: str
    created_at: str
    
    class Config:
        from_attributes = True


@router.post("", response_model=SignalResponse)
async def create_signal(
    signal: SignalCreate,
    db: AsyncSession,
) -> SignalResponse:
    """
    Register a new marketing signal/opportunity.
    
    Can be detected by Scout, manual input, research, etc.
    """
    new_signal = Signal(
        title=signal.title,
        url=signal.url,
        source=signal.source,
        relevance_score=signal.relevance_score,
        kg_node_id=signal.kg_node_id,
        status=SignalStatus.new,
    )
    
    db.add(new_signal)
    await db.flush()
    
    logger.info(f"Signal created: {new_signal.id} ({signal.title})")
    return SignalResponse.model_validate(new_signal)


@router.get("", response_model=List[SignalResponse])
async def list_signals(
    db: AsyncSession,
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    pillar_id: Optional[int] = Query(None),
    min_relevance: Optional[float] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
) -> List[SignalResponse]:
    """
    List marketing signals with optional filtering.
    
    Query params:
      - source: Filter by source (scout, manual, etc.)
      - status: Filter by status (new, read, used, archived)
      - pillar_id: Filter by pillar (1-6)
      - min_relevance: Filter by min relevance score (0.0-1.0)
      - limit: Max results (default 50, max 100)
      - offset: Pagination offset (default 0)
    """
    query = select(Signal).order_by(desc(Signal.detected_at))
    
    if source:
        query = query.where(Signal.source == source)
    
    if status:
        query = query.where(Signal.status == status)
    
    if pillar_id is not None:
        query = query.where(Signal.pillar_id == pillar_id)
    
    if min_relevance is not None:
        query = query.where(Signal.relevance_score >= min_relevance)
    
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    signals = result.scalars().all()
    
    return [SignalResponse.model_validate(s) for s in signals]


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: int,
    db: AsyncSession,
) -> SignalResponse:
    """Get a single signal by ID."""
    query = select(Signal).where(Signal.id == signal_id)
    result = await db.execute(query)
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    
    return SignalResponse.model_validate(signal)


@router.patch("/{signal_id}", response_model=SignalResponse)
async def update_signal_status(
    signal_id: int,
    update: SignalStatusUpdate,
    db: AsyncSession,
) -> SignalResponse:
    """Update a signal's status (read, used, archived, etc.)."""
    query = select(Signal).where(Signal.id == signal_id)
    result = await db.execute(query)
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    
    try:
        signal.status = SignalStatus(update.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{update.status}'. Must be one of: new, read, used, archived"
        )
    
    await db.commit()
    logger.info(f"Signal {signal_id} status updated to: {update.status}")
    
    return SignalResponse.model_validate(signal)


@router.delete("/{signal_id}")
async def delete_signal(
    signal_id: int,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Delete a signal."""
    query = select(Signal).where(Signal.id == signal_id)
    result = await db.execute(query)
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    
    await db.delete(signal)
    await db.commit()
    logger.info(f"Signal deleted: {signal_id}")
    
    return {"status": "ok", "deleted_id": signal_id}
