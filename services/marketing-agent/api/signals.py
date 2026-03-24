"""Marketing signals API — detect and register marketing opportunities."""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel

from ..models import Signal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["signals"])


class SignalCreate(BaseModel):
    """Create signal request."""
    title: str
    url: Optional[str] = None
    source: str  # scout, manual, research, etc.
    relevance_score: float = 0.5  # 0.0-1.0
    kg_node_id: Optional[str] = None


class SignalUpdate(BaseModel):
    """Update signal request."""
    title: Optional[str] = None
    url: Optional[str] = None
    relevance_score: Optional[float] = None
    kg_node_id: Optional[str] = None


class SignalResponse(BaseModel):
    """Signal response."""
    id: int
    title: str
    url: Optional[str]
    source: str
    relevance_score: float
    kg_node_id: Optional[str]
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
    )
    
    db.add(new_signal)
    await db.flush()
    
    logger.info(f"Signal created: {new_signal.id} ({signal.title})")
    return SignalResponse.model_validate(new_signal)


@router.get("", response_model=List[SignalResponse])
async def list_signals(
    db: AsyncSession,
    source: Optional[str] = Query(None),
    min_relevance: Optional[float] = Query(None),
    limit: int = Query(50, le=100),
    skip: int = Query(0),
) -> List[SignalResponse]:
    """
    List marketing signals with optional filtering.
    
    Query params:
      - source: Filter by source (scout, manual, etc.)
      - min_relevance: Filter by min relevance score (0.0-1.0)
      - limit: Max results (default 50, max 100)
      - skip: Pagination offset
    """
    query = select(Signal).order_by(Signal.created_at.desc())
    
    if source:
        query = query.where(Signal.source == source)
    
    if min_relevance is not None:
        query = query.where(Signal.relevance_score >= min_relevance)
    
    query = query.limit(limit).offset(skip)
    
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


@router.put("/{signal_id}", response_model=SignalResponse)
async def update_signal(
    signal_id: int,
    update: SignalUpdate,
    db: AsyncSession,
) -> SignalResponse:
    """Update a signal."""
    query = select(Signal).where(Signal.id == signal_id)
    result = await db.execute(query)
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(signal, key, value)
    
    await db.flush()
    logger.info(f"Signal updated: {signal_id}")
    
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
    logger.info(f"Signal deleted: {signal_id}")
    
    return {"status": "ok", "deleted_id": signal_id}
