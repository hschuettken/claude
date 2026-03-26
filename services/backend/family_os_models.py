"""
Family OS Phase 3 — Shared Decisions Data Models

Models for couple voting, decision history, and conflict resolution.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================

class DecisionStatus(str, Enum):
    """Decision workflow status."""
    OPEN = "open"           # Awaiting votes
    RESOLVED = "resolved"   # Voting closed, outcome determined
    ARCHIVED = "archived"   # Old decision, no longer relevant


class VotingMethod(str, Enum):
    """Voting method options."""
    BINARY = "binary"              # Yes/No
    RANKED_CHOICE = "ranked_choice" # 1st/2nd/3rd choice
    WEIGHTED = "weighted"           # Weighted voting


class ResolutionMethod(str, Enum):
    """How the decision was finally made."""
    CONSENSUS = "consensus"          # Everyone agreed
    MAJORITY = "majority"            # >50% won
    WEIGHTED_VOTE = "weighted_vote"  # Votes weighted by confidence
    DISCUSSION = "discussion"        # Talked it out
    COMPROMISE = "compromise"        # Hybrid solution


class ConflictType(str, Enum):
    """Type of conflict in decision-making."""
    DISAGREEMENT = "disagreement"           # Different preferences
    STALEMATE = "stalemate"                 # Tied votes / no consensus
    COMPETING_VALUES = "competing_values"   # Different value systems
    RESOURCE_CONSTRAINT = "resource_constraint"  # Budget/time/feasibility


# ============================================================================
# Decision Models
# ============================================================================

class DecisionCreateRequest(BaseModel):
    """Request to create a new decision."""
    title: str = Field(..., min_length=1, description="What needs to be decided?")
    description: Optional[str] = Field(None, description="Full context")
    category: str = Field("general", description="finance, home, travel, lifestyle, general")
    voting_method: VotingMethod = Field(VotingMethod.BINARY, description="How to vote")
    options: Optional[list[str]] = Field(
        None,
        description="For ranked_choice: list of options. For binary: ['Yes', 'No']"
    )
    deadline: Optional[datetime] = Field(None, description="When votes must be cast")


class DecisionResponse(BaseModel):
    """Decision with metadata."""
    id: UUID
    household_id: UUID
    title: str
    description: Optional[str]
    category: str
    status: DecisionStatus
    voting_method: VotingMethod
    options: list[str] = []
    created_by: UUID
    created_at: datetime
    deadline: Optional[datetime]
    resolved_at: Optional[datetime]
    final_outcome: Optional[str]
    resolution_notes: Optional[str]
    vote_count: int = 0  # Number of votes cast
    is_unanimous: bool = False  # All votes the same?


class DecisionListResponse(BaseModel):
    """List of decisions."""
    decisions: list[DecisionResponse]
    total: int
    open_count: int
    resolved_count: int


# ============================================================================
# Vote Models
# ============================================================================

class VoteCreateRequest(BaseModel):
    """Cast a vote on a decision."""
    vote_value: str = Field(..., description="'yes'/'no' or ranked choice array")
    rationale: Optional[str] = Field(None, description="Why this vote?")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="0.0-1.0: how sure?")


class VoteResponse(BaseModel):
    """Individual vote record."""
    id: UUID
    decision_id: UUID
    voter_id: UUID
    voter_name: str  # For display
    vote_value: str
    rationale: Optional[str]
    confidence: float
    created_at: datetime


class VoteSummaryResponse(BaseModel):
    """Summary of all votes on a decision."""
    decision_id: UUID
    total_votes: int
    votes_needed: int  # For quorum (typically 2 for couple)
    votes: list[VoteResponse]
    vote_counts: dict[str, int] = {}  # {"yes": 1, "no": 1} for binary
    consensus_reached: bool
    winner: Optional[str]  # Which option won


# ============================================================================
# Decision History Models
# ============================================================================

class DecisionHistoryCreateRequest(BaseModel):
    """Archive a resolved decision to history."""
    decision_id: UUID
    resolution_method: ResolutionMethod = Field(..., description="How was it decided?")
    impact_assessment: Optional[str] = Field(None, description="Was it the right call?")
    learned_lessons: list[str] = Field(default_factory=list)


class DecisionHistoryResponse(BaseModel):
    """Historical record of a decided decision."""
    id: UUID
    household_id: UUID
    decision_id: UUID
    original_title: str
    voting_summary: dict[str, str]  # {"Henning": "yes", "Nicole": "no"}
    final_outcome: str
    resolution_method: ResolutionMethod
    impact_assessment: Optional[str]
    learned_lessons: list[str]
    resolved_at: datetime
    created_at: datetime


class DecisionHistoryListResponse(BaseModel):
    """List historical decisions."""
    history: list[DecisionHistoryResponse]
    total: int
    average_resolution_method: str  # Most common method


# ============================================================================
# Conflict Resolution Models
# ============================================================================

class ConflictResolutionResponse(BaseModel):
    """Conflict resolution suggestion."""
    id: UUID
    decision_id: UUID
    conflict_type: ConflictType
    severity: float = Field(..., ge=1.0, le=10.0, description="1.0-10.0 severity")
    user1_position: str
    user2_position: str
    suggested_resolution: dict[str, Any]  # Type, details, rationale
    source: str  # "ai_generated", "rule_based", "manual"
    accepted: bool
    created_at: datetime


class ConflictAnalysisRequest(BaseModel):
    """Request AI to analyze a conflicted decision."""
    decision_id: UUID
    additional_context: Optional[str] = None


class ConflictAnalysisResponse(BaseModel):
    """AI analysis of a conflict."""
    decision_id: UUID
    conflict_type: ConflictType
    severity: float
    root_causes: list[str]
    suggested_resolutions: list[dict[str, Any]]  # Multiple options
    recommended_approach: str  # Which one is best?
    reasoning: str  # Why these suggestions?


# ============================================================================
# Household Stats
# ============================================================================

class HouseholdStatsResponse(BaseModel):
    """Household decision-making statistics."""
    household_id: UUID
    total_decisions: int
    open_decisions: int
    resolved_decisions: int
    archived_decisions: int
    consensus_rate: float  # % of decisions with unanim vote
    avg_voting_method: str  # Most common voting method
    members: list[dict[str, Any]]  # Names, roles, vote counts
    recent_decisions: list[DecisionResponse]
    recent_conflicts: list[ConflictResolutionResponse]
