"""
Storyline Map API — 12-week horizontal timeline management.

Endpoints:
- POST /storylines — Create new storyline
- GET /storylines — List all storylines
- GET /storylines/{id} — Get storyline with visualization data
- PATCH /storylines/{id} — Update storyline metadata
- DELETE /storylines/{id} — Archive/delete storyline

- POST /storylines/{id}/slots — Auto-populate week slots
- GET /storylines/{id}/visualization — Get 12-week timeline + pillar distribution
- PUT /storylines/{id}/slots/{week} — Drag-to-reschedule (assign draft to week)
- GET /storylines/{id}/arc-narrative — Get arc narrative view
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from ..models import Storyline, StorylineSlot, Draft, ContentPillar, Topic

router = APIRouter(prefix="/storylines", tags=["storylines"])


# ===========================
# Pydantic Models (Request/Response)
# ===========================

class StorylineSlotResponse(BaseModel):
    """Single week slot in the timeline."""
    id: int
    week_number: int
    publish_date: Optional[datetime]
    draft_id: Optional[int]
    pillar_id: Optional[int]
    status: str
    last_rescheduled_at: Optional[datetime]
    rescheduled_by: Optional[str]
    
    class Config:
        from_attributes = True


class StorylineCreate(BaseModel):
    """Create a new storyline."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    start_week: int = Field(..., ge=1, le=52)  # ISO week (1-52)
    duration_weeks: int = Field(default=12, ge=1, le=52)
    arc_hook: Optional[str] = None
    arc_theme: Optional[str] = None
    arc_resolution: Optional[str] = None
    pillar_distribution: Optional[Dict[str, float]] = None  # {pillar_id: pct, ...}


class StorylineUpdate(BaseModel):
    """Update storyline metadata."""
    name: Optional[str] = None
    description: Optional[str] = None
    arc_hook: Optional[str] = None
    arc_theme: Optional[str] = None
    arc_resolution: Optional[str] = None
    pillar_distribution: Optional[Dict[str, float]] = None
    status: Optional[str] = None  # draft, active, paused, archived


class StorylineResponse(BaseModel):
    """Full storyline with slots."""
    id: int
    name: str
    description: Optional[str]
    start_week: int
    duration_weeks: int
    arc_hook: Optional[str]
    arc_theme: Optional[str]
    arc_resolution: Optional[str]
    pillar_distribution: Dict[str, float]
    status: str
    slots: List[StorylineSlotResponse] = []
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class RescheduleRequest(BaseModel):
    """Drag-to-reschedule: move draft to new week."""
    draft_id: int
    from_week: int
    to_week: int
    rescheduled_by: str = "henning"


class PillarDistribution(BaseModel):
    """Pillar distribution visualization."""
    pillar_id: int
    pillar_name: str
    target_percentage: float
    actual_percentage: float
    color: Optional[str]
    assigned_slots: int
    total_slots: int


class TimelineVisualization(BaseModel):
    """12-week timeline visualization data."""
    storyline_id: int
    storyline_name: str
    start_week: int
    end_week: int
    weeks: List[Dict[str, Any]]  # Week-by-week breakdown
    pillar_distribution: List[PillarDistribution]
    coverage_rate: float  # % of slots filled
    
    class Config:
        from_attributes = True


class ArcNarrativeView(BaseModel):
    """Story arc narrative structure."""
    storyline_id: int
    storyline_name: str
    hook: Optional[str]
    theme: Optional[str]
    resolution: Optional[str]
    acts: List[Dict[str, Any]]  # Act breakdown (weeks 1-4, 5-8, 9-12)
    
    class Config:
        from_attributes = True


# ===========================
# API Endpoints
# ===========================

@router.post("", response_model=StorylineResponse, status_code=status.HTTP_201_CREATED)
async def create_storyline(
    req: StorylineCreate,
    db: AsyncSession,
) -> StorylineResponse:
    """Create a new 12-week storyline with empty slots."""
    
    # Validate pillar distribution sums to ~1.0 if provided
    if req.pillar_distribution:
        total = sum(req.pillar_distribution.values())
        if not (0.99 <= total <= 1.01):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pillar distribution must sum to 1.0 (got {total:.2f})"
            )
    
    # Create storyline
    storyline = Storyline(
        name=req.name,
        description=req.description,
        start_week=req.start_week,
        duration_weeks=req.duration_weeks,
        arc_hook=req.arc_hook,
        arc_theme=req.arc_theme,
        arc_resolution=req.arc_resolution,
        pillar_distribution=req.pillar_distribution or {},
        status="draft",
    )
    
    db.add(storyline)
    await db.flush()
    
    # Create empty week slots (1 to duration_weeks)
    for week_num in range(1, req.duration_weeks + 1):
        # Calculate publish date: start_week + (week_num - 1) weeks
        publish_date = datetime.utcnow() + timedelta(weeks=req.start_week + week_num - 2)
        
        slot = StorylineSlot(
            storyline_id=storyline.id,
            week_number=week_num,
            publish_date=publish_date,
            status="open",
        )
        db.add(slot)
    
    await db.commit()
    await db.refresh(storyline, ["slots"])
    
    return StorylineResponse.model_validate(storyline)


@router.get("", response_model=List[StorylineResponse])
async def list_storylines(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    limit: int = 100,
) -> List[StorylineResponse]:
    """List all storylines, optionally filtered by status."""
    
    query = select(Storyline).options(selectinload(Storyline.slots))
    
    if status_filter:
        query = query.where(Storyline.status == status_filter)
    
    query = query.order_by(Storyline.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    storylines = result.scalars().all()
    
    return [StorylineResponse.model_validate(s) for s in storylines]


@router.get("/{storyline_id}", response_model=StorylineResponse)
async def get_storyline(
    storyline_id: int,
    db: AsyncSession,
) -> StorylineResponse:
    """Get a specific storyline with all slots."""
    
    query = select(Storyline).where(Storyline.id == storyline_id).options(selectinload(Storyline.slots))
    result = await db.execute(query)
    storyline = result.scalar_one_or_none()
    
    if not storyline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyline not found")
    
    return StorylineResponse.model_validate(storyline)


@router.patch("/{storyline_id}", response_model=StorylineResponse)
async def update_storyline(
    storyline_id: int,
    req: StorylineUpdate,
    db: AsyncSession,
) -> StorylineResponse:
    """Update storyline metadata."""
    
    query = select(Storyline).where(Storyline.id == storyline_id).options(selectinload(Storyline.slots))
    result = await db.execute(query)
    storyline = result.scalar_one_or_none()
    
    if not storyline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyline not found")
    
    # Update fields
    if req.name:
        storyline.name = req.name
    if req.description is not None:
        storyline.description = req.description
    if req.arc_hook is not None:
        storyline.arc_hook = req.arc_hook
    if req.arc_theme is not None:
        storyline.arc_theme = req.arc_theme
    if req.arc_resolution is not None:
        storyline.arc_resolution = req.arc_resolution
    if req.pillar_distribution is not None:
        storyline.pillar_distribution = req.pillar_distribution
    if req.status:
        storyline.status = req.status
    
    storyline.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(storyline, ["slots"])
    
    return StorylineResponse.model_validate(storyline)


@router.delete("/{storyline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storyline(
    storyline_id: int,
    db: AsyncSession,
):
    """Archive/delete a storyline."""
    
    query = select(Storyline).where(Storyline.id == storyline_id)
    result = await db.execute(query)
    storyline = result.scalar_one_or_none()
    
    if not storyline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyline not found")
    
    # Soft delete: mark as archived
    storyline.status = "archived"
    storyline.updated_at = datetime.utcnow()
    
    await db.commit()


# ===========================
# Visualization Endpoints
# ===========================

@router.get("/{storyline_id}/visualization", response_model=TimelineVisualization)
async def get_timeline_visualization(
    storyline_id: int,
    db: AsyncSession,
) -> TimelineVisualization:
    """
    Get 12-week timeline visualization data.
    
    Returns:
    - Week-by-week breakdown (week number, publish date, assigned draft, pillar)
    - Pillar distribution (target vs actual)
    - Coverage rate (% of slots filled)
    """
    
    query = select(Storyline).where(Storyline.id == storyline_id).options(
        selectinload(Storyline.slots).selectinload(StorylineSlot.draft)
    )
    result = await db.execute(query)
    storyline = result.scalar_one_or_none()
    
    if not storyline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyline not found")
    
    # Build week-by-week breakdown
    weeks = []
    pillar_count = {}
    filled_slots = 0
    
    for slot in storyline.slots:
        draft_info = None
        if slot.draft:
            draft_info = {
                "id": slot.draft.id,
                "title": slot.draft.title,
                "platform": slot.draft.platform,
                "status": slot.draft.status,
            }
        
        week_data = {
            "week_number": slot.week_number,
            "publish_date": slot.publish_date.isoformat() if slot.publish_date else None,
            "draft": draft_info,
            "pillar_id": slot.pillar_id,
            "status": slot.status,
        }
        weeks.append(week_data)
        
        # Count pillar usage
        if slot.pillar_id:
            pillar_count[str(slot.pillar_id)] = pillar_count.get(str(slot.pillar_id), 0) + 1
        
        if slot.status != "open":
            filled_slots += 1
    
    # Build pillar distribution visualization
    total_slots = len(storyline.slots)
    pillar_distribution = []
    
    # Fetch all pillars from database
    pillar_query = select(ContentPillar).order_by(ContentPillar.kg_id)
    pillar_result = await db.execute(pillar_query)
    pillars = pillar_result.scalars().all()
    
    for pillar in pillars:
        pillar_id_str = str(pillar.kg_id)
        actual_count = pillar_count.get(pillar_id_str, 0)
        actual_pct = (actual_count / total_slots * 100) if total_slots > 0 else 0
        target_pct = (storyline.pillar_distribution.get(pillar_id_str, 0) * 100) if storyline.pillar_distribution else 0
        
        dist = PillarDistribution(
            pillar_id=pillar.kg_id,
            pillar_name=pillar.name,
            target_percentage=target_pct,
            actual_percentage=actual_pct,
            color=pillar.color,
            assigned_slots=actual_count,
            total_slots=total_slots,
        )
        pillar_distribution.append(dist)
    
    coverage_rate = (filled_slots / total_slots * 100) if total_slots > 0 else 0
    
    return TimelineVisualization(
        storyline_id=storyline.id,
        storyline_name=storyline.name,
        start_week=storyline.start_week,
        end_week=storyline.start_week + storyline.duration_weeks - 1,
        weeks=weeks,
        pillar_distribution=pillar_distribution,
        coverage_rate=coverage_rate,
    )


@router.get("/{storyline_id}/arc-narrative", response_model=ArcNarrativeView)
async def get_arc_narrative(
    storyline_id: int,
    db: AsyncSession,
) -> ArcNarrativeView:
    """
    Get story arc narrative view.
    
    Breaks 12-week arc into 3 acts (weeks 1-4, 5-8, 9-12) with narrative structure.
    """
    
    query = select(Storyline).where(Storyline.id == storyline_id).options(
        selectinload(Storyline.slots).selectinload(StorylineSlot.draft)
    )
    result = await db.execute(query)
    storyline = result.scalar_one_or_none()
    
    if not storyline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyline not found")
    
    # Divide into 3 acts
    weeks_per_act = len(storyline.slots) // 3
    acts = [
        {"act": 1, "weeks": "1-4", "slots": []},
        {"act": 2, "weeks": "5-8", "slots": []},
        {"act": 3, "weeks": "9-12", "slots": []},
    ]
    
    for slot in storyline.slots:
        act_idx = (slot.week_number - 1) // weeks_per_act
        if act_idx >= len(acts):
            act_idx = len(acts) - 1
        
        slot_data = {
            "week": slot.week_number,
            "draft_title": slot.draft.title if slot.draft else None,
            "pillar_id": slot.pillar_id,
            "status": slot.status,
        }
        acts[act_idx]["slots"].append(slot_data)
    
    return ArcNarrativeView(
        storyline_id=storyline.id,
        storyline_name=storyline.name,
        hook=storyline.arc_hook,
        theme=storyline.arc_theme,
        resolution=storyline.arc_resolution,
        acts=acts,
    )


# ===========================
# Drag-to-Reschedule Endpoint
# ===========================

@router.put("/{storyline_id}/slots/{week_number}", response_model=StorylineSlotResponse)
async def reschedule_slot(
    storyline_id: int,
    week_number: int,
    req: RescheduleRequest,
    db: AsyncSession,
) -> StorylineSlotResponse:
    """
    Drag-to-reschedule: assign a draft to a week slot or move draft between weeks.
    
    Implementation:
    1. Fetch the target slot (storyline_id, week_number)
    2. If draft_id provided, assign it to this slot
    3. Update last_rescheduled_at and rescheduled_by
    4. If moving from another slot, clear source slot
    """
    
    # Fetch target slot
    slot_query = select(StorylineSlot).where(
        and_(
            StorylineSlot.storyline_id == storyline_id,
            StorylineSlot.week_number == week_number,
        )
    )
    slot_result = await db.execute(slot_query)
    slot = slot_result.scalar_one_or_none()
    
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slot not found for week {week_number}"
        )
    
    # If request specifies from_week, clear source slot
    if req.from_week and req.from_week != week_number:
        source_query = select(StorylineSlot).where(
            and_(
                StorylineSlot.storyline_id == storyline_id,
                StorylineSlot.week_number == req.from_week,
            )
        )
        source_result = await db.execute(source_query)
        source_slot = source_result.scalar_one_or_none()
        
        if source_slot and source_slot.draft_id == req.draft_id:
            source_slot.draft_id = None
            source_slot.status = "open"
    
    # Assign draft to target slot
    slot.draft_id = req.draft_id
    slot.status = "assigned" if req.draft_id else "open"
    slot.last_rescheduled_at = datetime.utcnow()
    slot.rescheduled_by = req.rescheduled_by
    
    await db.commit()
    await db.refresh(slot)
    
    return StorylineSlotResponse.model_validate(slot)
