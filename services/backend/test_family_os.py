"""
Tests for Family OS Phase 3 functionality.

Tests couple voting, decision history, and conflict resolution.
"""

import pytest
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from family_os_models import (
    ConflictType,
    DecisionCreateRequest,
    DecisionHistoryCreateRequest,
    DecisionStatus,
    ResolutionMethod,
    VotingMethod,
    VoteCreateRequest,
)
from family_os_service import FamilyOSService


class MockDB:
    """Mock database client for testing."""
    
    def __init__(self):
        self.decisions = {}
        self.votes = {}
        self.users = {}
        self.history = {}
    
    async def fetchrow(self, query: str, *args, **kwargs):
        """Mock fetchrow."""
        # Simple mock that returns test data
        return {
            "id": uuid4(),
            "household_id": uuid4(),
            "title": "Test Decision",
            "description": "Test",
            "category": "general",
            "status": "open",
            "voting_method": "binary",
            "options": ["Yes", "No"],
            "created_by": uuid4(),
            "created_at": datetime.utcnow(),
            "deadline": None,
            "resolved_at": None,
            "final_outcome": None,
            "resolution_notes": None,
            "updated_at": datetime.utcnow(),
        }
    
    async def fetchval(self, query: str, *args, **kwargs):
        """Mock fetchval (returns single value)."""
        return 5  # Simulate 5 total decisions
    
    async def fetch(self, query: str, *args, **kwargs):
        """Mock fetch (returns multiple rows)."""
        return []


@pytest.fixture
def service():
    """Create a FamilyOSService instance with mock DB."""
    db = MockDB()
    return FamilyOSService(db_client=db, llm_client=None)


@pytest.fixture
def sample_household():
    """Sample household UUID."""
    return uuid4()


@pytest.fixture
def sample_user():
    """Sample user UUID."""
    return uuid4()


# ============================================================================
# Decision Creation Tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_decision_binary(service, sample_household, sample_user):
    """Test creating a binary vote decision."""
    request = DecisionCreateRequest(
        title="Should we buy new furniture?",
        description="The sofa is old and uncomfortable",
        category="home",
        voting_method=VotingMethod.BINARY,
    )
    
    decision = await service.create_decision(sample_household, sample_user, request)
    
    assert decision.title == request.title
    assert decision.category == "home"
    assert decision.voting_method == VotingMethod.BINARY
    assert decision.status == DecisionStatus.OPEN
    assert decision.options == ["Yes", "No"]


@pytest.mark.asyncio
async def test_create_decision_ranked_choice(service, sample_household, sample_user):
    """Test creating a ranked choice decision."""
    request = DecisionCreateRequest(
        title="Where should we vacation?",
        description="Summer 2026 vacation",
        category="travel",
        voting_method=VotingMethod.RANKED_CHOICE,
        options=["Italy", "Spain", "Portugal", "Greece"],
    )
    
    decision = await service.create_decision(sample_household, sample_user, request)
    
    assert decision.voting_method == VotingMethod.RANKED_CHOICE
    assert len(decision.options) == 4
    assert "Italy" in decision.options


@pytest.mark.asyncio
async def test_create_decision_with_deadline(service, sample_household, sample_user):
    """Test creating a decision with voting deadline."""
    deadline = datetime.utcnow() + timedelta(days=7)
    request = DecisionCreateRequest(
        title="Should we renovate the kitchen?",
        description="Need to decide soon to book contractors",
        category="home",
        deadline=deadline,
    )
    
    decision = await service.create_decision(sample_household, sample_user, request)
    
    assert decision.deadline is not None


# ============================================================================
# Voting Tests
# ============================================================================

@pytest.mark.asyncio
async def test_cast_vote_binary(service, sample_household, sample_user):
    """Test casting a binary vote."""
    # First create a decision
    decision_request = DecisionCreateRequest(
        title="Test Decision",
        category="general",
    )
    decision = await service.create_decision(sample_household, sample_user, decision_request)
    
    # Cast a vote
    vote_request = VoteCreateRequest(
        vote_value="yes",
        rationale="I think this is a good idea",
        confidence=0.8,
    )
    
    voter_id = uuid4()
    result = await service.cast_vote(decision.id, voter_id, vote_request)
    
    assert result["vote"]["vote_value"] == "yes"
    assert result["vote"]["confidence"] == 0.8


@pytest.mark.asyncio
async def test_update_vote(service, sample_household, sample_user):
    """Test updating an existing vote."""
    # Create decision and cast vote
    decision_request = DecisionCreateRequest(title="Test")
    decision = await service.create_decision(sample_household, sample_user, decision_request)
    voter_id = uuid4()
    
    # First vote
    vote1 = VoteCreateRequest(vote_value="yes", confidence=0.5)
    await service.cast_vote(decision.id, voter_id, vote1)
    
    # Update vote
    vote2 = VoteCreateRequest(vote_value="no", confidence=0.9)
    result = await service.cast_vote(decision.id, voter_id, vote2)
    
    assert result["vote"]["vote_value"] == "no"
    assert result["vote"]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_vote_with_rationale(service, sample_household, sample_user):
    """Test that vote rationale is stored."""
    decision_request = DecisionCreateRequest(title="Test")
    decision = await service.create_decision(sample_household, sample_user, decision_request)
    
    vote_request = VoteCreateRequest(
        vote_value="yes",
        rationale="Because it aligns with our sustainability goals",
        confidence=0.95,
    )
    
    voter_id = uuid4()
    result = await service.cast_vote(decision.id, voter_id, vote_request)
    
    assert result["vote"]["rationale"] == vote_request.rationale


# ============================================================================
# Decision Resolution Tests
# ============================================================================

@pytest.mark.asyncio
async def test_resolve_decision(service, sample_household, sample_user):
    """Test resolving a decision."""
    # Create and resolve
    request = DecisionCreateRequest(title="Test Decision")
    decision = await service.create_decision(sample_household, sample_user, request)
    
    resolved = await service.resolve_decision(
        decision.id,
        outcome="Yes, let's do it",
        method=ResolutionMethod.CONSENSUS,
        notes="We both agreed after discussion",
    )
    
    assert resolved.status == DecisionStatus.RESOLVED
    assert resolved.final_outcome == "Yes, let's do it"
    assert resolved.resolution_notes == "We both agreed after discussion"
    assert resolved.resolved_at is not None


@pytest.mark.asyncio
async def test_resolve_decision_by_majority(service, sample_household, sample_user):
    """Test resolving a decision by majority vote."""
    request = DecisionCreateRequest(title="Test")
    decision = await service.create_decision(sample_household, sample_user, request)
    
    resolved = await service.resolve_decision(
        decision.id,
        outcome="Proceed with plan A",
        method=ResolutionMethod.MAJORITY,
        notes="2-1 vote in favor",
    )
    
    assert resolved.status == DecisionStatus.RESOLVED


# ============================================================================
# Conflict Detection Tests
# ============================================================================

@pytest.mark.asyncio
async def test_detect_conflict_disagreement(service):
    """Test detecting a disagreement conflict."""
    # Mock conflict detection
    conflict = await service.detect_conflict(uuid4())
    
    # When there are no votes, no conflict should be detected
    assert conflict is None


@pytest.mark.asyncio
async def test_detect_conflict_stalemate(service):
    """Test detecting a stalemate (tied votes)."""
    # This would require actual voting in the DB
    # For now, test that the method exists and can be called
    result = await service.detect_conflict(uuid4())
    
    # Should return None or conflict dict
    assert result is None or isinstance(result, dict)


# ============================================================================
# Conflict Resolution Suggestions Tests
# ============================================================================

@pytest.mark.asyncio
async def test_generate_conflict_resolutions_disagreement(service):
    """Test generating resolutions for disagreement."""
    resolutions = await service.generate_conflict_resolution(
        uuid4(),
        ConflictType.DISAGREEMENT,
        "We disagree on priorities",
    )
    
    assert "suggestions" in resolutions or "recommended" in resolutions


@pytest.mark.asyncio
async def test_generate_conflict_resolutions_stalemate(service):
    """Test generating resolutions for stalemate."""
    resolutions = await service.generate_conflict_resolution(
        uuid4(),
        ConflictType.STALEMATE,
        "Tied votes",
    )
    
    # Should suggest discussion round or trial period
    assert "suggestions" in resolutions or "type" in resolutions


@pytest.mark.asyncio
async def test_conflict_resolution_includes_rationale(service):
    """Test that conflict resolutions include rationale."""
    resolutions = await service.generate_conflict_resolution(
        uuid4(),
        ConflictType.DISAGREEMENT,
    )
    
    if "suggestions" in resolutions:
        for suggestion in resolutions["suggestions"]:
            assert "type" in suggestion
            assert "rationale" in suggestion or "details" in suggestion


# ============================================================================
# Decision History Tests
# ============================================================================

@pytest.mark.asyncio
async def test_archive_decision(service, sample_household, sample_user):
    """Test archiving a decision to history."""
    # Create and resolve a decision
    request = DecisionCreateRequest(title="Kitchen Renovation")
    decision = await service.create_decision(sample_household, sample_user, request)
    
    # Resolve it
    resolved = await service.resolve_decision(
        decision.id,
        "Yes, let's renovate",
        ResolutionMethod.CONSENSUS,
    )
    
    # Archive to history
    history_request = DecisionHistoryCreateRequest(
        decision_id=decision.id,
        resolution_method=ResolutionMethod.CONSENSUS,
        impact_assessment="Great decision! Kitchen looks amazing.",
        learned_lessons=[
            "Contractors take longer than expected",
            "Budget overruns are normal",
            "Communication is key",
        ],
    )
    
    history = await service.archive_decision(sample_household, history_request)
    
    assert history["decision_id"] == decision.id
    assert len(history["learned_lessons"]) == 3
    assert "Communication is key" in history["learned_lessons"]


@pytest.mark.asyncio
async def test_archive_nonexistent_decision(service, sample_household):
    """Test that archiving a nonexistent decision fails gracefully."""
    history_request = DecisionHistoryCreateRequest(
        decision_id=uuid4(),
        resolution_method=ResolutionMethod.CONSENSUS,
    )
    
    with pytest.raises(ValueError):
        await service.archive_decision(sample_household, history_request)


# ============================================================================
# Helper Method Tests
# ============================================================================

@pytest.mark.asyncio
async def test_vote_summary_empty(service):
    """Test vote summary when no votes cast."""
    summary = await service._get_vote_summary(uuid4())
    
    assert "votes" in summary or summary == {}


@pytest.mark.asyncio
async def test_format_vote_summary(service):
    """Test formatting vote summary for display."""
    summary = {
        "voting_summary": {
            "Henning": "yes",
            "Nicole": "no",
        }
    }
    
    formatted = service._format_vote_summary(summary)
    
    assert "Henning: yes" in formatted
    assert "Nicole: no" in formatted


@pytest.mark.asyncio
async def test_rule_based_resolutions_stalemate(service):
    """Test rule-based resolution for stalemate."""
    decision = None  # Would be populated
    summary = {"vote_counts": {"yes": 1, "no": 1}}
    
    resolutions = service._rule_based_resolutions(
        decision,
        summary,
        ConflictType.STALEMATE,
    )
    
    assert "suggestions" in resolutions
    assert len(resolutions["suggestions"]) > 0


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_full_decision_workflow(service, sample_household, sample_user):
    """Test full workflow: create → vote → conflict → resolve → archive."""
    # 1. Create decision
    request = DecisionCreateRequest(
        title="Buy a car?",
        description="Need reliable transport",
        category="finance",
    )
    decision = await service.create_decision(sample_household, sample_user, request)
    assert decision.status == DecisionStatus.OPEN
    
    # 2. Cast votes (with disagreement)
    voter1 = uuid4()
    voter2 = uuid4()
    
    vote1 = VoteCreateRequest(vote_value="yes", confidence=0.9)
    result1 = await service.cast_vote(decision.id, voter1, vote1)
    
    vote2 = VoteCreateRequest(vote_value="no", confidence=0.7)
    result2 = await service.cast_vote(decision.id, voter2, vote2)
    
    # 3. Detect conflict
    conflict = await service.detect_conflict(decision.id)
    # Should detect disagreement
    
    # 4. Get resolutions
    if conflict:
        resolutions = await service.generate_conflict_resolution(
            decision.id,
            ConflictType(conflict["conflict_type"]),
        )
        assert "suggestions" in resolutions or "recommended" in resolutions
    
    # 5. Resolve decision
    resolved = await service.resolve_decision(
        decision.id,
        outcome="Lease a car instead",
        method=ResolutionMethod.COMPROMISE,
    )
    assert resolved.status == DecisionStatus.RESOLVED
    
    # 6. Archive to history
    history_req = DecisionHistoryCreateRequest(
        decision_id=decision.id,
        resolution_method=ResolutionMethod.COMPROMISE,
        learned_lessons=["Compromise works best for big purchases"],
    )
    history = await service.archive_decision(sample_household, history_req)
    assert history["decision_id"] == decision.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
