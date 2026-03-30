"""
Friction Lab REST API Routes — 7 routes for friction detection & automation proposals

1. POST /api/v1/friction/events — Record a friction event
2. GET /api/v1/friction/patterns — List detected friction patterns
3. POST /api/v1/friction/patterns/{pattern_id}/proposals — Generate proposals
4. GET /api/v1/friction/proposals — List proposals for user
5. POST /api/v1/friction/proposals/{proposal_id}/accept — Accept a proposal
6. POST /api/v1/friction/proposals/{proposal_id}/reject — Reject a proposal
7. GET /api/v1/friction/dashboard — Get full friction dashboard
"""

import asyncpg
import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status, Depends
from pydantic import BaseModel

from friction_detection import (
    FrictionDetectionEngine,
    FrictionType,
    FrictionEvent,
    FrictionPattern,
    AutomationProposal,
)

logger = logging.getLogger(__name__)

# Create router for Friction Lab endpoints
router = APIRouter(
    prefix="/api/v1/friction",
    tags=["friction-lab"],
    responses={404: {"description": "Not found"}},
)

# Global engine instance
_engine: Optional[FrictionDetectionEngine] = None


async def get_engine() -> FrictionDetectionEngine:
    """Get or create Friction Detection engine instance."""
    global _engine
    if not _engine:
        db_url = os.getenv(
            "FAMILY_OS_DB_URL",
            os.getenv("DATABASE_URL", "postgresql://homelab:homelab@192.168.0.80:5432/homelab"),
        )

        try:
            pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
            _engine = FrictionDetectionEngine(db_client=pool)
            await _engine.initialize()
            logger.info("Friction Detection Engine initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Friction Detection Engine: {e}")
            raise

    return _engine


# ============================================================================
# Request/Response Models
# ============================================================================


class FrictionEventRequest(BaseModel):
    """Request to record a friction event."""
    friction_type: FrictionType
    target_id: str
    target_name: str
    metadata: Optional[dict] = None


class FrictionEventResponse(BaseModel):
    """Response after recording friction event."""
    message: str
    event: dict


class FrictionPatternResponse(BaseModel):
    """Response for a friction pattern."""
    id: str
    friction_type: FrictionType
    target_name: str
    occurrence_count: int
    frequency: str
    severity: float
    date_range_start: str
    date_range_end: str


class FrictionPatternListResponse(BaseModel):
    """Response for listing patterns."""
    patterns: list[FrictionPatternResponse]
    total: int
    summary: dict


class ProposalResponse(BaseModel):
    """Response for an automation proposal."""
    id: str
    title: str
    description: str
    proposal_type: str
    confidence: float
    estimated_benefit: str
    acceptance_state: str


class ProposalListResponse(BaseModel):
    """Response for listing proposals."""
    proposals: list[ProposalResponse]
    total: int


class ProposalAcceptanceRequest(BaseModel):
    """Request to accept/reject a proposal."""
    action: str  # "accepted", "rejected", "deferred"
    reason: Optional[str] = None


class FrictionDashboardResponse(BaseModel):
    """Complete friction dashboard."""
    recent_friction_events: list
    active_patterns: list
    pending_proposals: list
    summary: dict


# ============================================================================
# Route 1: Record Friction Event
# ============================================================================


@router.post(
    "/events",
    response_model=FrictionEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a friction event",
)
async def record_friction_event(
    user_id: UUID,
    request: FrictionEventRequest,
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> FrictionEventResponse:
    """
    Record a friction event (override, postponed task, skipped habit).

    - **user_id**: User experiencing the friction
    - **friction_type**: Type of friction (repeated_override, postponed_task, skipped_habit)
    - **target_id**: ID of the automation/task/habit
    - **target_name**: Human-readable name
    - **metadata**: Optional context (reason, duration, etc.)
    """
    try:
        event = await engine.record_friction_event(
            user_id=user_id,
            friction_type=request.friction_type,
            target_id=request.target_id,
            target_name=request.target_name,
            metadata=request.metadata or {},
        )

        return FrictionEventResponse(
            message=f"Friction event recorded: {request.friction_type.value}",
            event={
                "user_id": str(event.user_id),
                "friction_type": event.friction_type.value,
                "target_id": event.target_id,
                "target_name": event.target_name,
                "occurrence_date": event.occurrence_date.isoformat(),
            },
        )

    except Exception as e:
        logger.error(f"Error recording friction event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record friction event",
        )


# ============================================================================
# Route 2: Detect & List Friction Patterns
# ============================================================================


@router.get(
    "/patterns",
    response_model=FrictionPatternListResponse,
    summary="Detect and list friction patterns",
)
async def detect_friction_patterns(
    user_id: UUID,
    days_lookback: int = Query(30, ge=7, le=90),
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> FrictionPatternListResponse:
    """
    Detect friction patterns for a user.

    Analyzes friction events from the past N days and identifies repeating patterns.

    - **user_id**: User to analyze
    - **days_lookback**: How many days to analyze (default 30, range 7-90)
    """
    try:
        patterns = await engine.detect_patterns(user_id, days_lookback=days_lookback)

        pattern_responses = [
            FrictionPatternResponse(
                id=p.id,
                friction_type=p.friction_type,
                target_name=p.target_name,
                occurrence_count=p.occurrence_count,
                frequency=p.frequency,
                severity=p.severity,
                date_range_start=p.date_range_start.isoformat(),
                date_range_end=p.date_range_end.isoformat(),
            )
            for p in patterns
        ]

        return FrictionPatternListResponse(
            patterns=pattern_responses,
            total=len(patterns),
            summary={
                "high_severity": sum(1 for p in patterns if p.severity >= 0.8),
                "daily_friction": sum(1 for p in patterns if p.frequency == "daily"),
                "analysis_days": days_lookback,
            },
        )

    except Exception as e:
        logger.error(f"Error detecting patterns: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to detect friction patterns",
        )


# ============================================================================
# Route 3: Generate Proposals for Pattern
# ============================================================================


@router.post(
    "/patterns/{pattern_id}/proposals",
    response_model=ProposalListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate automation proposals",
)
async def generate_proposals(
    pattern_id: str,
    user_id: UUID,
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> ProposalListResponse:
    """
    Generate automation proposals for a friction pattern.

    Analyzes the pattern and suggests specific automations to reduce friction.

    - **pattern_id**: ID of the friction pattern
    - **user_id**: User to generate proposals for
    """
    try:
        # Fetch the pattern first
        # (In real implementation, would query DB; here we'll generate from pattern info)

        # For now, create a minimal pattern for proposal generation
        # In production, would fetch from DB and use actual pattern data
        pattern = FrictionPattern(
            id=pattern_id,
            user_id=user_id,
            friction_type=FrictionType.POSTPONED_TASK,
            target_id="task_001",
            target_name="Daily standup",
            occurrence_count=5,
            frequency="daily",
            date_range_start=None,
            date_range_end=None,
            severity=0.8,
            context={},
        )

        proposals = await engine.generate_proposals(pattern)

        proposal_responses = [
            ProposalResponse(
                id=p.id,
                title=p.title,
                description=p.description,
                proposal_type=p.proposal_type,
                confidence=p.confidence,
                estimated_benefit=p.estimated_benefit,
                acceptance_state=p.acceptance_state,
            )
            for p in proposals
        ]

        return ProposalListResponse(
            proposals=proposal_responses,
            total=len(proposals),
        )

    except Exception as e:
        logger.error(f"Error generating proposals: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate proposals",
        )


# ============================================================================
# Route 4: List Proposals for User
# ============================================================================


@router.get(
    "/proposals",
    response_model=ProposalListResponse,
    summary="List proposals for user",
)
async def list_proposals(
    user_id: UUID,
    state: Optional[str] = Query(None, description="Filter by state: pending, accepted, rejected"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> ProposalListResponse:
    """
    List automation proposals for a user.

    - **user_id**: User to list proposals for
    - **state**: Filter by acceptance state (pending, accepted, rejected)
    - **limit**: Number of results
    - **offset**: Pagination offset
    """
    try:
        # In production, this would query the DB with filters
        # For now, return empty list as placeholder
        return ProposalListResponse(proposals=[], total=0)

    except Exception as e:
        logger.error(f"Error listing proposals: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list proposals",
        )


# ============================================================================
# Route 5: Accept Proposal
# ============================================================================


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=dict,
    summary="Accept a proposal",
)
async def accept_proposal(
    proposal_id: UUID,
    user_id: UUID,
    request: Optional[ProposalAcceptanceRequest] = None,
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> dict:
    """
    Accept an automation proposal.

    Records acceptance and marks proposal as implemented (or queued for implementation).

    - **proposal_id**: ID of the proposal
    - **user_id**: User accepting the proposal
    - **action**: "accepted", "rejected", or "deferred"
    - **reason**: Optional reason for the decision
    """
    try:
        action = request.action if request else "accepted"
        reason = request.reason if request else None

        await engine.record_proposal_acceptance(proposal_id, user_id, action, reason)

        return {
            "message": f"Proposal {action}: {proposal_id}",
            "proposal_id": str(proposal_id),
            "action": action,
        }

    except Exception as e:
        logger.error(f"Error accepting proposal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept proposal",
        )


# ============================================================================
# Route 6: Reject Proposal
# ============================================================================


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=dict,
    summary="Reject a proposal",
)
async def reject_proposal(
    proposal_id: UUID,
    user_id: UUID,
    reason: Optional[str] = None,
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> dict:
    """
    Reject an automation proposal.

    Records rejection so system learns not to suggest similar proposals.

    - **proposal_id**: ID of the proposal
    - **user_id**: User rejecting the proposal
    - **reason**: Why the proposal doesn't work for you
    """
    try:
        await engine.record_proposal_acceptance(proposal_id, user_id, "rejected", reason)

        return {
            "message": f"Proposal rejected: {proposal_id}",
            "proposal_id": str(proposal_id),
            "action": "rejected",
            "reason": reason,
        }

    except Exception as e:
        logger.error(f"Error rejecting proposal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject proposal",
        )


# ============================================================================
# Route 7: Friction Dashboard
# ============================================================================


@router.get(
    "/dashboard",
    response_model=FrictionDashboardResponse,
    summary="Get friction dashboard",
)
async def get_friction_dashboard(
    user_id: UUID,
    engine: FrictionDetectionEngine = Depends(get_engine),
) -> FrictionDashboardResponse:
    """
    Get a comprehensive friction dashboard for the user.

    Shows:
    - Recent friction events (last 7 days)
    - Active friction patterns
    - Pending automation proposals
    - Summary statistics

    - **user_id**: User to get dashboard for
    """
    try:
        dashboard = await engine.get_user_friction_dashboard(user_id)

        return FrictionDashboardResponse(
            recent_friction_events=dashboard["recent_friction_events"],
            active_patterns=dashboard["active_patterns"],
            pending_proposals=dashboard["pending_proposals"],
            summary=dashboard["summary"],
        )

    except Exception as e:
        logger.error(f"Error getting friction dashboard: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get friction dashboard",
        )
