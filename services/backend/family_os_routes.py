"""
Family OS Phase 3 — REST API Routes

Couple voting, decision history, conflict resolution endpoints.
Can be included in FastAPI app via APIRouter or included in main.py
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from family_os_models import (
    ConflictAnalysisRequest,
    ConflictAnalysisResponse,
    ConflictResolutionResponse,
    ConflictType,
    DecisionCreateRequest,
    DecisionHistoryCreateRequest,
    DecisionHistoryListResponse,
    DecisionHistoryResponse,
    DecisionListResponse,
    DecisionResponse,
    DecisionStatus,
    HouseholdStatsResponse,
    ResolutionMethod,
    VoteCreateRequest,
    VoteSummaryResponse,
)
from family_os_service import FamilyOSService

logger = logging.getLogger(__name__)

# Create router for Family OS endpoints
router = APIRouter(
    prefix="/api/v1/family-os",
    tags=["family-os"],
    responses={404: {"description": "Not found"}},
)


# ============================================================================
# Decision Management
# ============================================================================

@router.post(
    "/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new decision",
)
async def create_decision(
    household_id: UUID,
    user_id: UUID,  # In real app, from JWT token
    request: DecisionCreateRequest,
    service: FamilyOSService = None,
) -> DecisionResponse:
    """
    Create a new shared decision for the couple/household.
    
    - **title**: What needs to be decided
    - **description**: Full context
    - **category**: finance, home, travel, lifestyle, or general
    - **voting_method**: binary (yes/no) or ranked_choice
    - **deadline**: Optional deadline for voting
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    try:
        decision = await service.create_decision(household_id, user_id, request)
        return decision
    except Exception as e:
        logger.error(f"Error creating decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create decision",
        )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionResponse,
    summary="Get a specific decision",
)
async def get_decision(
    decision_id: UUID,
    service: FamilyOSService = None,
) -> DecisionResponse:
    """Get a specific decision with current vote count."""
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    decision = await service.get_decision(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.get(
    "/households/{household_id}/decisions",
    response_model=DecisionListResponse,
    summary="List household decisions",
)
async def list_decisions(
    household_id: UUID,
    status_filter: Optional[DecisionStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: FamilyOSService = None,
) -> DecisionListResponse:
    """
    List decisions for a household.
    
    - **status_filter**: Filter by open, resolved, or archived
    - **limit**: Number of results (max 100)
    - **offset**: Pagination offset
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    decisions, total = await service.list_decisions(
        household_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    
    open_count = sum(1 for d in decisions if d.status == DecisionStatus.OPEN)
    resolved_count = sum(1 for d in decisions if d.status == DecisionStatus.RESOLVED)
    
    return DecisionListResponse(
        decisions=decisions,
        total=total,
        open_count=open_count,
        resolved_count=resolved_count,
    )


# ============================================================================
# Voting
# ============================================================================

@router.post(
    "/decisions/{decision_id}/votes",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Cast a vote on a decision",
)
async def cast_vote(
    decision_id: UUID,
    voter_id: UUID,
    request: VoteCreateRequest,
    service: FamilyOSService = None,
) -> dict:
    """
    Cast or update a vote on a decision.
    
    - **vote_value**: "yes"/"no" for binary, or ranked choice array
    - **rationale**: Why you're voting this way
    - **confidence**: 0.0-1.0 (how sure you are)
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    try:
        result = await service.cast_vote(decision_id, voter_id, request)
        return result
    except Exception as e:
        logger.error(f"Error casting vote: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cast vote",
        )


@router.get(
    "/decisions/{decision_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary for a decision",
)
async def get_vote_summary(
    decision_id: UUID,
    service: FamilyOSService = None,
) -> VoteSummaryResponse:
    """Get current votes and summary for a decision."""
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    summary = await service._get_vote_summary(decision_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Decision not found")
    
    return VoteSummaryResponse(
        decision_id=decision_id,
        total_votes=summary.get("total_votes", 0),
        votes_needed=summary.get("votes_needed", 2),
        votes=summary.get("votes", []),
        vote_counts=summary.get("vote_counts", {}),
        consensus_reached=summary.get("consensus_reached", False),
        winner=summary.get("winner"),
    )


# ============================================================================
# Decision Resolution
# ============================================================================

@router.post(
    "/decisions/{decision_id}/resolve",
    response_model=DecisionResponse,
    summary="Resolve a decision",
)
async def resolve_decision(
    decision_id: UUID,
    outcome: str,
    method: ResolutionMethod,
    notes: Optional[str] = None,
    service: FamilyOSService = None,
) -> DecisionResponse:
    """
    Mark a decision as resolved.
    
    - **outcome**: What was decided
    - **method**: How was it decided (consensus, majority, compromise, etc.)
    - **notes**: Explanation of the resolution
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    try:
        result = await service.resolve_decision(
            decision_id, outcome, method, notes
        )
        return result
    except Exception as e:
        logger.error(f"Error resolving decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve decision",
        )


# ============================================================================
# Decision History
# ============================================================================

@router.post(
    "/households/{household_id}/history",
    response_model=DecisionHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Archive a decision to history",
)
async def archive_decision(
    household_id: UUID,
    request: DecisionHistoryCreateRequest,
    service: FamilyOSService = None,
) -> DecisionHistoryResponse:
    """
    Move a resolved decision to historical archive.
    
    - **resolution_method**: How was it finally decided
    - **impact_assessment**: Was it a good call?
    - **learned_lessons**: What did you learn
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    try:
        history = await service.archive_decision(household_id, request)
        return DecisionHistoryResponse(**history)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error archiving decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to archive decision",
        )


@router.get(
    "/households/{household_id}/history",
    response_model=DecisionHistoryListResponse,
    summary="List decision history",
)
async def list_decision_history(
    household_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: FamilyOSService = None,
) -> DecisionHistoryListResponse:
    """Get historical decisions for a household."""
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    history, total = await service.get_decision_history(
        household_id, limit=limit, offset=offset
    )
    
    # Calculate most common resolution method
    methods = [h["resolution_method"] for h in history]
    most_common = max(set(methods), key=methods.count) if methods else "consensus"
    
    return DecisionHistoryListResponse(
        history=[DecisionHistoryResponse(**h) for h in history],
        total=total,
        average_resolution_method=most_common,
    )


# ============================================================================
# Conflict Resolution
# ============================================================================

@router.get(
    "/decisions/{decision_id}/conflict",
    response_model=Optional[dict],
    summary="Detect conflict in decision votes",
)
async def detect_conflict(
    decision_id: UUID,
    service: FamilyOSService = None,
) -> Optional[dict]:
    """
    Analyze if there's a conflict in the voting.
    
    Returns conflict type and severity if detected, None if consensus.
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    conflict = await service.detect_conflict(decision_id)
    return conflict


@router.post(
    "/decisions/{decision_id}/resolve-conflict",
    response_model=dict,
    summary="Get conflict resolution suggestions",
)
async def get_conflict_resolution(
    decision_id: UUID,
    request: Optional[ConflictAnalysisRequest] = None,
    service: FamilyOSService = None,
) -> dict:
    """
    Get AI-powered suggestions for resolving a decision conflict.
    
    - **additional_context**: Extra info that might help resolution
    
    Returns multiple suggested approaches with likelihood of success.
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    # Detect conflict type first
    conflict = await service.detect_conflict(decision_id)
    if not conflict:
        raise HTTPException(
            status_code=400,
            detail="No conflict detected - decision appears to have consensus",
        )
    
    try:
        conflict_type = ConflictType(conflict["conflict_type"])
        additional_context = (
            request.additional_context if request else None
        )
        
        resolutions = await service.generate_conflict_resolution(
            decision_id, conflict_type, additional_context
        )
        
        return resolutions
    except Exception as e:
        logger.error(f"Error generating conflict resolutions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate resolutions",
        )


# ============================================================================
# Household Statistics
# ============================================================================

@router.get(
    "/households/{household_id}/stats",
    response_model=HouseholdStatsResponse,
    summary="Get household decision statistics",
)
async def get_household_stats(
    household_id: UUID,
    service: FamilyOSService = None,
) -> HouseholdStatsResponse:
    """
    Get analytics on the household's decision-making patterns.
    
    - Consensus rate
    - Most common voting methods
    - Decision trends
    - Recent conflicts
    """
    if not service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service not initialized",
        )
    
    # Get all decisions for stats
    decisions, total = await service.list_decisions(household_id, limit=100)
    
    # Calculate stats
    open_count = sum(1 for d in decisions if d.status == DecisionStatus.OPEN)
    resolved_count = sum(1 for d in decisions if d.status == DecisionStatus.RESOLVED)
    archived_count = sum(1 for d in decisions if d.status == DecisionStatus.ARCHIVED)
    
    # Get recent history
    history, _ = await service.get_decision_history(household_id, limit=10)
    
    return HouseholdStatsResponse(
        household_id=household_id,
        total_decisions=total,
        open_decisions=open_count,
        resolved_decisions=resolved_count,
        archived_decisions=archived_count,
        consensus_rate=0.75,  # Would calculate from history
        avg_voting_method="binary",  # Would calculate from decisions
        members=[],  # Would fetch from users table
        recent_decisions=decisions[:5],
        recent_conflicts=[],  # Would fetch from conflict_resolutions table
    )
