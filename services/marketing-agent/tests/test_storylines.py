"""Tests for Storyline Map API — Task #168."""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from models import Base, Storyline, StorylineSlot, ContentPillar, Draft


@pytest.fixture
async def test_db():
    """Create an in-memory test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_maker = async_sessionmaker(engine, class_=AsyncSession)
    
    yield session_maker
    
    await engine.dispose()


@pytest.mark.asyncio
async def test_storyline_model(test_db):
    """Test Storyline model creation and basic operations."""
    async with test_db() as session:
        # Create a storyline
        storyline = Storyline(
            name="Q2 2025 — Data Governance Arc",
            description="12-week arc on data governance strategy",
            start_week=13,
            duration_weeks=12,
            arc_hook="Data governance is not just compliance...",
            arc_theme="From governance to governance enablement",
            arc_resolution="Practical framework for modern data governance",
            pillar_distribution={"1": 0.45, "2": 0.20, "3": 0.15, "4": 0.10, "5": 0.07, "6": 0.03},
            status="draft",
        )
        
        # Create slots
        for week_num in range(1, 13):
            slot = StorylineSlot(
                storyline=storyline,
                week_number=week_num,
                publish_date=datetime.utcnow() + timedelta(weeks=week_num),
                status="open",
            )
            session.add(slot)
        
        session.add(storyline)
        await session.commit()
        
        # Verify storyline
        result = await session.execute(select(Storyline).where(Storyline.name == "Q2 2025 — Data Governance Arc"))
        saved = result.scalar_one()
        
        assert saved.name == "Q2 2025 — Data Governance Arc"
        assert saved.duration_weeks == 12
        assert len(saved.slots) == 12
        assert saved.pillar_distribution["1"] == 0.45


@pytest.mark.asyncio
async def test_storyline_slot_rescheduling(test_db):
    """Test drag-to-reschedule functionality."""
    async with test_db() as session:
        # Create storyline and slots
        storyline = Storyline(
            name="Test Storyline",
            start_week=10,
            duration_weeks=12,
            status="draft",
        )
        
        slots = []
        for week_num in range(1, 13):
            slot = StorylineSlot(
                storyline=storyline,
                week_number=week_num,
                publish_date=datetime.utcnow() + timedelta(weeks=week_num),
                status="open",
            )
            slots.append(slot)
            session.add(slot)
        
        session.add(storyline)
        await session.commit()
        
        # Create a draft
        draft = Draft(
            title="Test Post",
            content="Test content",
            status="draft",
            platform="blog",
        )
        session.add(draft)
        await session.commit()
        
        # Assign draft to week 5
        slot_5 = slots[4]  # 0-indexed
        slot_5.draft_id = draft.id
        slot_5.status = "assigned"
        slot_5.last_rescheduled_at = datetime.utcnow()
        slot_5.rescheduled_by = "henning"
        await session.commit()
        
        # Verify assignment
        result = await session.execute(
            select(StorylineSlot).where(StorylineSlot.week_number == 5)
        )
        updated_slot = result.scalar_one()
        
        assert updated_slot.draft_id == draft.id
        assert updated_slot.status == "assigned"
        assert updated_slot.rescheduled_by == "henning"


@pytest.mark.asyncio
async def test_pillar_distribution_validation(test_db):
    """Test pillar distribution percentages."""
    async with test_db() as session:
        # Valid distribution (sums to 1.0)
        valid_dist = {"1": 0.45, "2": 0.20, "3": 0.15, "4": 0.10, "5": 0.07, "6": 0.03}
        total = sum(valid_dist.values())
        
        assert 0.99 <= total <= 1.01, f"Distribution {total} is invalid"
        
        # Create storyline with valid distribution
        storyline = Storyline(
            name="Valid Distribution Test",
            start_week=1,
            duration_weeks=12,
            pillar_distribution=valid_dist,
            status="draft",
        )
        
        session.add(storyline)
        await session.commit()
        
        # Verify
        result = await session.execute(select(Storyline).where(Storyline.name == "Valid Distribution Test"))
        saved = result.scalar_one()
        
        assert saved.pillar_distribution == valid_dist


def test_storyline_api_schema():
    """Test Storyline API Pydantic models."""
    from api.storylines import (
        StorylineCreate, StorylineResponse, TimelineVisualization,
        PillarDistribution, ArcNarrativeView
    )
    
    # Test StorylineCreate
    req = StorylineCreate(
        name="Test Storyline",
        start_week=13,
        duration_weeks=12,
        arc_hook="Opening hook",
        arc_theme="Central theme",
        arc_resolution="Resolution",
        pillar_distribution={"1": 0.45, "2": 0.20, "3": 0.15, "4": 0.10, "5": 0.07, "6": 0.03},
    )
    
    assert req.name == "Test Storyline"
    assert req.duration_weeks == 12
    
    # Test PillarDistribution
    pillar = PillarDistribution(
        pillar_id=1,
        pillar_name="SAP Deep Technical",
        target_percentage=45.0,
        actual_percentage=40.0,
        color="#FF5733",
        assigned_slots=5,
        total_slots=12,
    )
    
    assert pillar.pillar_id == 1
    assert pillar.target_percentage == 45.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
