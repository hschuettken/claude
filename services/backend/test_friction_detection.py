"""
Tests for Friction Detection & Automation Proposal Engine

Tests:
1. Record friction events
2. Detect patterns from events
3. Generate automation proposals
4. Track proposal acceptance
5. Get friction dashboard
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from friction_detection import (
    FrictionDetectionEngine,
    FrictionType,
    FrictionEvent,
    FrictionPattern,
)

# Note: These tests assume a PostgreSQL database is available
# Set DATABASE_URL environment variable or use defaults


@pytest.fixture
async def engine():
    """Create and initialize friction engine."""
    import asyncpg
    
    db_url = "postgresql://homelab:homelab@192.168.0.80:5432/homelab"
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
        engine = FrictionDetectionEngine(db_client=pool)
        await engine.initialize()
        yield engine
        await pool.close()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


@pytest.mark.asyncio
async def test_record_friction_event(engine):
    """Test recording a friction event."""
    user_id = uuid4()
    
    event = await engine.record_friction_event(
        user_id=user_id,
        friction_type=FrictionType.REPEATED_OVERRIDE,
        target_id="automation_001",
        target_name="HVAC Schedule",
        metadata={"reason": "Too cold"},
    )
    
    assert event.user_id == user_id
    assert event.friction_type == FrictionType.REPEATED_OVERRIDE
    assert event.target_name == "HVAC Schedule"
    assert event.metadata["reason"] == "Too cold"


@pytest.mark.asyncio
async def test_detect_patterns(engine):
    """Test pattern detection from multiple events."""
    user_id = uuid4()
    
    # Record multiple friction events for the same target
    for i in range(5):
        await engine.record_friction_event(
            user_id=user_id,
            friction_type=FrictionType.POSTPONED_TASK,
            target_id="task_001",
            target_name="Daily standup",
            metadata={"reason": "Too early"},
        )
    
    # Detect patterns
    patterns = await engine.detect_patterns(user_id, days_lookback=30)
    
    assert len(patterns) >= 1
    pattern = patterns[0]
    assert pattern.friction_type == FrictionType.POSTPONED_TASK
    assert pattern.target_name == "Daily standup"
    assert pattern.occurrence_count >= 5
    assert pattern.severity > 0.0


@pytest.mark.asyncio
async def test_generate_proposals(engine):
    """Test proposal generation for friction patterns."""
    user_id = uuid4()
    
    # Record multiple friction events
    for i in range(3):
        await engine.record_friction_event(
            user_id=user_id,
            friction_type=FrictionType.SKIPPED_HABIT,
            target_id="habit_001",
            target_name="Morning meditation",
            metadata={},
        )
    
    # Detect pattern
    patterns = await engine.detect_patterns(user_id, days_lookback=30)
    assert len(patterns) >= 1
    
    # Generate proposals for first pattern
    proposals = await engine.generate_proposals(patterns[0])
    
    assert len(proposals) > 0
    for proposal in proposals:
        assert proposal.title is not None
        assert proposal.description is not None
        assert 0.0 <= proposal.confidence <= 1.0
        assert proposal.acceptance_state == "pending"


@pytest.mark.asyncio
async def test_proposal_acceptance_tracking(engine):
    """Test tracking of proposal acceptance/rejection."""
    user_id = uuid4()
    proposal_id = uuid4()
    
    # Record acceptance
    await engine.record_proposal_acceptance(
        proposal_id=proposal_id,
        user_id=user_id,
        action="accepted",
        reason="This will definitely help",
    )
    
    # Verify it was recorded (in real test, would query DB)
    # This is a simple smoke test to ensure no exception


@pytest.mark.asyncio
async def test_friction_dashboard(engine):
    """Test getting friction dashboard."""
    user_id = uuid4()
    
    # Record some friction events
    for i in range(2):
        await engine.record_friction_event(
            user_id=user_id,
            friction_type=FrictionType.REPEATED_OVERRIDE,
            target_id="auto_001",
            target_name="AC Control",
            metadata={},
        )
    
    # Get dashboard
    dashboard = await engine.get_user_friction_dashboard(user_id)
    
    assert dashboard["user_id"] == str(user_id)
    assert "recent_friction_events" in dashboard
    assert "active_patterns" in dashboard
    assert "pending_proposals" in dashboard
    assert "summary" in dashboard


@pytest.mark.asyncio
async def test_friction_type_enum():
    """Test FrictionType enum."""
    assert FrictionType.REPEATED_OVERRIDE.value == "repeated_override"
    assert FrictionType.POSTPONED_TASK.value == "postponed_task"
    assert FrictionType.SKIPPED_HABIT.value == "skipped_habit"
    assert FrictionType.CONTRADICTORY_BEHAVIOR.value == "contradictory_behavior"


def test_friction_event_dataclass():
    """Test FrictionEvent dataclass creation."""
    user_id = uuid4()
    event = FrictionEvent(
        user_id=user_id,
        friction_type=FrictionType.POSTPONED_TASK,
        target_id="task_123",
        target_name="Test Task",
        occurrence_date=datetime.utcnow(),
        metadata={"test": True},
    )
    
    assert event.user_id == user_id
    assert event.friction_type == FrictionType.POSTPONED_TASK
    assert event.metadata["test"] is True


def test_friction_pattern_dataclass():
    """Test FrictionPattern dataclass creation."""
    user_id = uuid4()
    pattern = FrictionPattern(
        id="pattern_001",
        user_id=user_id,
        friction_type=FrictionType.SKIPPED_HABIT,
        target_id="habit_001",
        target_name="Morning routine",
        occurrence_count=5,
        frequency="daily",
        date_range_start=datetime.utcnow() - timedelta(days=7),
        date_range_end=datetime.utcnow(),
        severity=0.8,
        context={"notes": "Critical"},
    )
    
    assert pattern.occurrence_count == 5
    assert pattern.frequency == "daily"
    assert pattern.severity == 0.8


if __name__ == "__main__":
    # Run with: pytest test_friction_detection.py -v
    pytest.main([__file__, "-v"])
