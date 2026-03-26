"""
Family OS Phase 3 — Service Logic

Handles couple voting, decision history, conflict resolution.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import asyncpg

from family_os_models import (
    ConflictType,
    DecisionCreateRequest,
    DecisionHistoryCreateRequest,
    DecisionResponse,
    DecisionStatus,
    ResolutionMethod,
    VotingMethod,
    VoteCreateRequest,
    VoteResponse,
)

logger = logging.getLogger(__name__)


class FamilyOSService:
    """Service for managing shared household decisions."""

    def __init__(self, db_client=None, llm_client=None):
        """
        Initialize FamilyOS service.
        
        Args:
            db_client: Database connection client (PostgreSQL pool or connection)
            llm_client: LLM client for generating conflict resolutions
        """
        self.db = db_client
        self.llm = llm_client

    # ========================================================================
    # Decision Management
    # ========================================================================

    async def create_decision(
        self,
        household_id: UUID,
        user_id: UUID,
        request: DecisionCreateRequest,
    ) -> DecisionResponse:
        """
        Create a new shared decision for the household.
        
        Args:
            household_id: Which household/couple
            user_id: Who is creating it
            request: Decision details
            
        Returns:
            DecisionResponse with the created decision
        """
        if request.voting_method == VotingMethod.BINARY and not request.options:
            request.options = ["Yes", "No"]

        query = """
            INSERT INTO family_os.decisions (
                household_id, title, description, category,
                status, voting_method, options, created_by, deadline
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8, $9
            )
            RETURNING id, household_id, title, description, category,
                      status, voting_method, options, created_by,
                      created_at, deadline, resolved_at, final_outcome,
                      resolution_notes, updated_at
        """
        
        # Use asyncpg syntax ($1, $2, etc.)
        async with self.db.acquire() as conn:
            result = await conn.fetchrow(
                query,
                household_id,
                request.title,
                request.description,
                request.category,
                DecisionStatus.OPEN.value,
                request.voting_method.value,
                json.dumps(request.options or []),
                user_id,
                request.deadline,
            )
        
        return self._row_to_decision(result)

    async def get_decision(self, decision_id: UUID) -> Optional[DecisionResponse]:
        """Get a specific decision with vote count."""
        query = """
            SELECT d.*, COUNT(v.id) as vote_count
            FROM family_os.decisions d
            LEFT JOIN family_os.votes v ON d.id = v.decision_id
            WHERE d.id = $1
            GROUP BY d.id
        """
        async with self.db.acquire() as conn:
            result = await conn.fetchrow(query, decision_id)
        
        if result:
            return self._row_to_decision(result)
        return None

    async def list_decisions(
        self,
        household_id: UUID,
        status: Optional[DecisionStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DecisionResponse], int]:
        """
        List decisions for a household.
        
        Args:
            household_id: Which household
            status: Filter by status (open/resolved/archived)
            limit: Pagination limit
            offset: Pagination offset
            
        Returns:
            Tuple of (decisions, total_count)
        """
        where_clause = "WHERE d.household_id = $1"
        params = [household_id]
        param_count = 1
        
        if status:
            param_count += 1
            where_clause += f" AND d.status = ${param_count}"
            params.append(status.value)

        # Get total count
        count_query = f"""
            SELECT COUNT(*) FROM family_os.decisions d
            {where_clause}
        """
        
        async with self.db.acquire() as conn:
            total = await conn.fetchval(count_query, *params)

            # Get paginated results with vote counts
            param_count += 1
            limit_param = param_count
            param_count += 1
            offset_param = param_count
            
            query = f"""
                SELECT d.*, COUNT(v.id) as vote_count
                FROM family_os.decisions d
                LEFT JOIN family_os.votes v ON d.id = v.decision_id
                {where_clause}
                GROUP BY d.id
                ORDER BY d.created_at DESC
                LIMIT ${limit_param} OFFSET ${offset_param}
            """
            params.extend([limit, offset])
            
            results = await conn.fetch(query, *params)
        
        decisions = [self._row_to_decision(row) for row in results]
        
        return decisions, total

    async def cast_vote(
        self,
        decision_id: UUID,
        voter_id: UUID,
        request: VoteCreateRequest,
    ) -> dict[str, Any]:
        """
        Cast or update a vote on a decision.
        
        Args:
            decision_id: Which decision to vote on
            voter_id: Who is voting
            request: Vote details
            
        Returns:
            Vote record and decision summary
        """
        # Upsert vote (replace if exists)
        query = """
            INSERT INTO family_os.votes (
                decision_id, voter_id, vote_value, rationale, confidence
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (decision_id, voter_id)
            DO UPDATE SET
                vote_value = EXCLUDED.vote_value,
                rationale = EXCLUDED.rationale,
                confidence = EXCLUDED.confidence,
                updated_at = NOW()
            RETURNING id, decision_id, voter_id, vote_value, rationale, confidence, created_at
        """
        
        async with self.db.acquire() as conn:
            vote = await conn.fetchrow(
                query,
                decision_id,
                voter_id,
                request.vote_value,
                request.rationale,
                request.confidence,
            )
        
        # Check if we now have consensus or need conflict resolution
        summary = await self._get_vote_summary(decision_id)
        
        if summary.get("consensus_reached"):
            logger.info(f"Consensus reached on decision {decision_id}")
        
        return {"vote": dict(vote), "summary": summary}

    async def resolve_decision(
        self,
        decision_id: UUID,
        outcome: str,
        method: ResolutionMethod,
        notes: Optional[str] = None,
    ) -> DecisionResponse:
        """
        Resolve a decision and move to resolved status.
        
        Args:
            decision_id: Which decision
            outcome: What was decided
            method: How was it decided
            notes: Resolution explanation
            
        Returns:
            Updated decision
        """
        query = """
            UPDATE family_os.decisions
            SET
                status = $1,
                final_outcome = $2,
                resolution_notes = $3,
                resolved_at = NOW(),
                updated_at = NOW()
            WHERE id = $4
            RETURNING id, household_id, title, description, category,
                      status, voting_method, options, created_by,
                      created_at, deadline, resolved_at, final_outcome,
                      resolution_notes, updated_at
        """
        
        async with self.db.acquire() as conn:
            result = await conn.fetchrow(
                query,
                DecisionStatus.RESOLVED.value,
                outcome,
                notes,
                decision_id,
            )
        
        return self._row_to_decision(result)

    # ========================================================================
    # Decision History
    # ========================================================================

    async def archive_decision(
        self,
        household_id: UUID,
        request: DecisionHistoryCreateRequest,
    ) -> dict[str, Any]:
        """
        Move a resolved decision to history with lessons learned.
        
        Args:
            household_id: Which household
            request: History details
            
        Returns:
            History record
        """
        # Get the decision first
        decision = await self.get_decision(request.decision_id)
        if not decision:
            raise ValueError(f"Decision {request.decision_id} not found")
        
        # Get vote summary for the record
        summary = await self._get_vote_summary(request.decision_id)
        
        # Create history record
        query = """
            INSERT INTO family_os.decision_history (
                household_id, decision_id, original_title,
                voting_summary, final_outcome, resolution_method,
                impact_assessment, learned_lessons, resolved_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, household_id, decision_id, original_title,
                      voting_summary, final_outcome, resolution_method,
                      impact_assessment, learned_lessons, resolved_at, created_at
        """
        
        async with self.db.acquire() as conn:
            result = await conn.fetchrow(
                query,
                household_id,
                request.decision_id,
                decision.title,
                json.dumps(summary.get("voting_summary", {})),
                decision.final_outcome,
                request.resolution_method.value,
                request.impact_assessment,
                json.dumps(request.learned_lessons),
                decision.resolved_at,
            )
        
        return {
            "id": str(result["id"]),
            "household_id": str(result["household_id"]),
            "decision_id": str(result["decision_id"]),
            "original_title": result["original_title"],
            "voting_summary": result["voting_summary"],
            "final_outcome": result["final_outcome"],
            "resolution_method": result["resolution_method"],
            "impact_assessment": result["impact_assessment"],
            "learned_lessons": result["learned_lessons"],
            "resolved_at": result["resolved_at"].isoformat() if result["resolved_at"] else None,
            "created_at": result["created_at"].isoformat() if result["created_at"] else None,
        }

    async def get_decision_history(
        self,
        household_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get historical decisions for a household."""
        count_query = """
            SELECT COUNT(*) FROM family_os.decision_history
            WHERE household_id = $1
        """
        
        query = """
            SELECT id, household_id, decision_id, original_title,
                   voting_summary, final_outcome, resolution_method,
                   impact_assessment, learned_lessons, resolved_at, created_at
            FROM family_os.decision_history
            WHERE household_id = $1
            ORDER BY resolved_at DESC
            LIMIT $2 OFFSET $3
        """
        
        async with self.db.acquire() as conn:
            total = await conn.fetchval(count_query, household_id)
            results = await conn.fetch(query, household_id, limit, offset)
        
        return [dict(row) for row in results], total

    # ========================================================================
    # Conflict Resolution
    # ========================================================================

    async def detect_conflict(self, decision_id: UUID) -> Optional[dict[str, Any]]:
        """
        Detect if there's a conflict in voting.
        
        Returns conflict type and severity if one exists.
        """
        summary = await self._get_vote_summary(decision_id)
        
        if summary.get("consensus_reached"):
            return None  # No conflict
        
        # Analyze the conflict
        votes = summary.get("votes", [])
        if len(votes) == 0:
            return None
        
        if len(votes) == 1:
            # Only one person voted, not really a conflict
            return None
        
        # Two people with different votes = disagreement
        vote_values = [v["vote_value"] for v in votes]
        
        if len(set(vote_values)) == 1:
            return None  # All same, no conflict
        
        # Determine conflict type and severity
        conflict_type = ConflictType.DISAGREEMENT
        severity = 5.0  # Default medium severity
        
        # Check confidence levels for severity
        confidences = [v.get("confidence", 1.0) for v in votes]
        if all(c >= 0.9 for c in confidences):
            severity = 8.0  # Both very confident = more serious
        
        if any(c <= 0.5 for c in confidences):
            severity = 3.0  # Someone uncertain = easier to resolve
        
        # Look for stalemate (tied votes)
        vote_counts = summary.get("vote_counts", {})
        if vote_counts:
            counts = list(vote_counts.values())
            if all(c == counts[0] for c in counts):
                conflict_type = ConflictType.STALEMATE
                severity = 7.0
        
        return {
            "conflict_type": conflict_type.value,
            "severity": severity,
            "vote_split": vote_counts,
        }

    async def generate_conflict_resolution(
        self,
        decision_id: UUID,
        conflict_type: ConflictType,
        additional_context: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate AI-powered conflict resolution suggestions.
        
        Args:
            decision_id: Which decision has the conflict
            conflict_type: Type of conflict detected
            additional_context: Extra info for LLM
            
        Returns:
            Suggested resolutions
        """
        decision = await self.get_decision(decision_id)
        summary = await self._get_vote_summary(decision_id)
        
        if not decision or not self.llm:
            # Fallback to rule-based suggestions
            return self._rule_based_resolutions(decision, summary, conflict_type)
        
        # Would call LLM here in production
        # For now, return rule-based suggestions
        return self._rule_based_resolutions(decision, summary, conflict_type)

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def _get_vote_summary(self, decision_id: UUID) -> dict[str, Any]:
        """Get current vote summary for a decision."""
        query = """
            SELECT
                d.id, d.voting_method, d.options,
                json_object_agg(u.name, v.vote_value) FILTER (WHERE v.id IS NOT NULL) as voting_summary,
                COUNT(v.id) as total_votes,
                d.status
            FROM family_os.decisions d
            LEFT JOIN family_os.votes v ON d.id = v.decision_id
            LEFT JOIN family_os.users u ON v.voter_id = u.id
            WHERE d.id = $1
            GROUP BY d.id, d.voting_method, d.options
        """
        
        votes_query = """
            SELECT
                v.id, v.decision_id, v.voter_id,
                u.name as voter_name, v.vote_value,
                v.rationale, v.confidence, v.created_at
            FROM family_os.votes v
            JOIN family_os.users u ON v.voter_id = u.id
            WHERE v.decision_id = $1
            ORDER BY v.created_at
        """
        
        async with self.db.acquire() as conn:
            result = await conn.fetchrow(query, decision_id)
            if not result:
                return {}
            
            votes = await conn.fetch(votes_query, decision_id)
        
        # Convert votes to list and count by value
        votes_list = []
        vote_counts = {}
        
        for v in votes:
            vote_dict = {
                "id": str(v["id"]),
                "decision_id": str(v["decision_id"]),
                "voter_id": str(v["voter_id"]),
                "voter_name": v["voter_name"],
                "vote_value": v["vote_value"],
                "rationale": v["rationale"],
                "confidence": float(v["confidence"]) if v["confidence"] else 1.0,
                "created_at": v["created_at"].isoformat() if v["created_at"] else None,
            }
            votes_list.append(vote_dict)
            
            val = v["vote_value"]
            vote_counts[val] = vote_counts.get(val, 0) + 1
        
        # Determine consensus and winner
        vote_values = [v["vote_value"] for v in votes_list]
        consensus = len(set(vote_values)) <= 1 and len(vote_values) > 0
        winner = max(vote_counts, key=vote_counts.get) if vote_counts else None
        
        # Parse voting_summary JSON
        voting_summary = result["voting_summary"]
        if isinstance(voting_summary, str):
            voting_summary = json.loads(voting_summary) if voting_summary else {}
        
        return {
            "decision_id": str(decision_id),
            "voting_summary": voting_summary or {},
            "total_votes": result["total_votes"],
            "votes": votes_list,
            "vote_counts": vote_counts,
            "consensus_reached": consensus,
            "winner": winner,
            "votes_needed": 2,  # For a couple
        }

    def _row_to_decision(self, row: dict[str, Any]) -> DecisionResponse:
        """Convert database row to DecisionResponse."""
        # Handle UUID conversion if needed
        decision_id = row["id"]
        if not isinstance(decision_id, UUID):
            decision_id = UUID(str(decision_id))
        
        household_id = row["household_id"]
        if not isinstance(household_id, UUID):
            household_id = UUID(str(household_id))
        
        created_by = row["created_by"]
        if not isinstance(created_by, UUID):
            created_by = UUID(str(created_by))
        
        # Handle options JSON
        options = row.get("options") or []
        if isinstance(options, str):
            options = json.loads(options)
        
        return DecisionResponse(
            id=decision_id,
            household_id=household_id,
            title=row["title"],
            description=row.get("description"),
            category=row.get("category", "general"),
            status=DecisionStatus(row["status"]),
            voting_method=VotingMethod(row["voting_method"]),
            options=options,
            created_by=created_by,
            created_at=row["created_at"],
            deadline=row.get("deadline"),
            resolved_at=row.get("resolved_at"),
            final_outcome=row.get("final_outcome"),
            resolution_notes=row.get("resolution_notes"),
            vote_count=row.get("vote_count", 0),
        )

    def _format_vote_summary(self, summary: dict[str, Any]) -> str:
        """Format vote summary for LLM."""
        lines = []
        for person, vote in (summary.get("voting_summary") or {}).items():
            lines.append(f"- {person}: {vote}")
        return "\n".join(lines) or "No votes yet"

    def _rule_based_resolutions(
        self,
        decision: DecisionResponse,
        summary: dict[str, Any],
        conflict_type: ConflictType,
    ) -> dict[str, Any]:
        """Generate rule-based conflict resolution suggestions."""
        suggestions = []
        
        if conflict_type == ConflictType.STALEMATE:
            suggestions.extend([
                {
                    "type": "discussion_round",
                    "details": "Have a structured discussion where each person gets 10 min uninterrupted",
                    "rationale": "Often reveals the real concerns vs. surface positions",
                    "likelihood": 0.7,
                },
                {
                    "type": "trial_period",
                    "details": "Pick one option, try it for 2 weeks, then re-evaluate",
                    "rationale": "Real-world data beats abstract argument",
                    "likelihood": 0.6,
                },
            ])
        elif conflict_type == ConflictType.DISAGREEMENT:
            suggestions.extend([
                {
                    "type": "find_shared_goal",
                    "details": "Look for underlying shared values (comfort, sustainability, etc.)",
                    "rationale": "Different paths often lead to same destination",
                    "likelihood": 0.8,
                },
                {
                    "type": "hybrid_solution",
                    "details": "Combine elements from both positions",
                    "rationale": "Often satisfies both",
                    "likelihood": 0.65,
                },
            ])
        
        return {
            "conflict_type": conflict_type.value,
            "suggestions": suggestions,
            "recommended": suggestions[0] if suggestions else None,
        }
