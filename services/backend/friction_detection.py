"""
Friction Detection & Automation Proposal Engine

Detects repeated user behaviors that indicate friction:
- Manual overrides of automations
- Postponed tasks (repeated snoozing)
- Skipped habits

Proposes automation improvements based on detected patterns.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import asyncpg
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FrictionType(str, Enum):
    """Types of friction detected in workflows."""
    REPEATED_OVERRIDE = "repeated_override"  # User manually overrides same automation
    POSTPONED_TASK = "postponed_task"  # User repeatedly postpones/snoozes a task
    SKIPPED_HABIT = "skipped_habit"  # User repeatedly skips the same habit
    CONTRADICTORY_BEHAVIOR = "contradictory_behavior"  # Behavior contradicts automation rules


@dataclass
class FrictionEvent:
    """A single friction-indicative event."""
    user_id: UUID
    friction_type: FrictionType
    target_id: str  # e.g., automation_id, task_id, habit_id
    target_name: str  # e.g., "Morning routine", "Daily standup"
    occurrence_date: datetime
    metadata: dict  # Additional context (e.g., why it was skipped)


@dataclass
class FrictionPattern:
    """A detected pattern of repeated friction."""
    id: str
    user_id: UUID
    friction_type: FrictionType
    target_id: str
    target_name: str
    occurrence_count: int
    frequency: str  # "daily", "weekly", "sporadic"
    date_range_start: datetime
    date_range_end: datetime
    severity: float  # 0.0-1.0: how much this is impacting user
    context: dict  # Additional contextual info


@dataclass
class AutomationProposal:
    """Proposed automation to reduce friction."""
    id: str
    friction_pattern_id: str
    proposal_type: str  # e.g., "adjust_schedule", "change_rules", "add_condition"
    title: str
    description: str
    rationale: str  # Why this would help
    confidence: float  # 0.0-1.0: how likely this is to solve the problem
    estimated_benefit: str  # e.g., "Save 5 min/day", "Reduce friction by 40%"
    acceptance_state: str  # "pending", "accepted", "rejected", "implemented"
    created_at: datetime
    accepted_at: Optional[datetime] = None
    implemented_at: Optional[datetime] = None


class FrictionDetectionEngine:
    """Main engine for detecting friction and proposing automations."""

    def __init__(self, db_client: asyncpg.Pool):
        self.db = db_client
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Create necessary tables."""
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create friction detection tables."""
        schema = """
        CREATE SCHEMA IF NOT EXISTS friction_lab;

        CREATE TABLE IF NOT EXISTS friction_lab.friction_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            friction_type VARCHAR(50) NOT NULL,
            target_id VARCHAR(255) NOT NULL,
            target_name VARCHAR(255) NOT NULL,
            occurrence_date TIMESTAMP WITH TIME ZONE DEFAULT now(),
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            FOREIGN KEY (user_id) REFERENCES family_os.users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS friction_lab.friction_patterns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            friction_type VARCHAR(50) NOT NULL,
            target_id VARCHAR(255) NOT NULL,
            target_name VARCHAR(255) NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            frequency VARCHAR(20),  -- daily, weekly, sporadic
            date_range_start TIMESTAMP WITH TIME ZONE,
            date_range_end TIMESTAMP WITH TIME ZONE,
            severity NUMERIC(3,2),  -- 0.00-1.00
            context JSONB DEFAULT '{}',
            detected_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            last_updated TIMESTAMP WITH TIME ZONE DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS friction_lab.automation_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            friction_pattern_id UUID NOT NULL,
            user_id UUID NOT NULL,
            proposal_type VARCHAR(100) NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            rationale TEXT,
            confidence NUMERIC(3,2),  -- 0.00-1.00
            estimated_benefit VARCHAR(255),
            acceptance_state VARCHAR(20) DEFAULT 'pending',  -- pending, accepted, rejected, implemented
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            accepted_at TIMESTAMP WITH TIME ZONE,
            implemented_at TIMESTAMP WITH TIME ZONE,
            FOREIGN KEY (user_id) REFERENCES family_os.users(id) ON DELETE CASCADE,
            FOREIGN KEY (friction_pattern_id) REFERENCES friction_lab.friction_patterns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS friction_lab.proposal_acceptance_tracking (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id UUID NOT NULL,
            user_id UUID NOT NULL,
            action VARCHAR(20) NOT NULL,  -- accepted, rejected, deferred
            reason TEXT,
            action_timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
            FOREIGN KEY (proposal_id) REFERENCES friction_lab.automation_proposals(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES family_os.users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_friction_events_user_type ON friction_lab.friction_events(user_id, friction_type);
        CREATE INDEX IF NOT EXISTS idx_friction_patterns_user ON friction_lab.friction_patterns(user_id);
        CREATE INDEX IF NOT EXISTS idx_proposals_user_state ON friction_lab.automation_proposals(user_id, acceptance_state);
        """

        try:
            async with self.db.acquire() as conn:
                await conn.execute(schema)
                self.logger.info("✅ Friction Lab tables initialized")
        except Exception as e:
            self.logger.warning(f"⚠️  Friction Lab table creation: {e}")

    async def record_friction_event(
        self,
        user_id: UUID,
        friction_type: FrictionType,
        target_id: str,
        target_name: str,
        metadata: dict = None,
    ) -> FrictionEvent:
        """Record a single friction event."""
        query = """
        INSERT INTO friction_lab.friction_events 
        (user_id, friction_type, target_id, target_name, metadata)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, user_id, friction_type, target_id, target_name, occurrence_date, metadata
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                user_id,
                friction_type.value,
                target_id,
                target_name,
                json.dumps(metadata or {}),
            )

        event = FrictionEvent(
            user_id=row["user_id"],
            friction_type=FrictionType(row["friction_type"]),
            target_id=row["target_id"],
            target_name=row["target_name"],
            occurrence_date=row["occurrence_date"],
            metadata=row["metadata"] or {},
        )

        self.logger.debug(f"Recorded friction event: {friction_type.value} for {target_name}")
        return event

    async def detect_patterns(self, user_id: UUID, days_lookback: int = 30) -> list[FrictionPattern]:
        """
        Detect friction patterns for a user based on recent events.

        Analyzes friction events from the past N days and clusters them to identify patterns.
        """
        query = """
        SELECT 
            friction_type, 
            target_id, 
            target_name, 
            COUNT(*) as occurrence_count,
            MIN(occurrence_date) as date_start,
            MAX(occurrence_date) as date_end
        FROM friction_lab.friction_events
        WHERE user_id = $1 
            AND occurrence_date > now() - interval '1 day' * $2
        GROUP BY friction_type, target_id, target_name
        HAVING COUNT(*) >= 2  -- Only patterns with at least 2 occurrences
        ORDER BY COUNT(*) DESC
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, user_id, days_lookback)

        patterns = []
        for row in rows:
            # Calculate severity based on frequency
            days_span = (row["date_end"] - row["date_start"]).days + 1
            frequency_per_day = row["occurrence_count"] / max(days_span, 1)

            # Severity: 0.5 for rare, 0.75 for weekly, 1.0 for daily
            if frequency_per_day >= 1.0:
                frequency = "daily"
                severity = 1.0
            elif frequency_per_day >= 0.3:
                frequency = "weekly"
                severity = 0.75
            else:
                frequency = "sporadic"
                severity = 0.5

            # Check if pattern already exists
            existing = await self._get_existing_pattern(
                user_id,
                FrictionType(row["friction_type"]),
                row["target_id"],
            )

            if existing:
                pattern_id = existing["id"]
                # Update existing pattern
                await self._update_pattern(
                    pattern_id,
                    row["occurrence_count"],
                    frequency,
                    severity,
                    row["date_start"],
                    row["date_end"],
                )
            else:
                pattern_id = await self._create_pattern(
                    user_id,
                    FrictionType(row["friction_type"]),
                    row["target_id"],
                    row["target_name"],
                    row["occurrence_count"],
                    frequency,
                    severity,
                    row["date_start"],
                    row["date_end"],
                )

            pattern = FrictionPattern(
                id=str(pattern_id),
                user_id=user_id,
                friction_type=FrictionType(row["friction_type"]),
                target_id=row["target_id"],
                target_name=row["target_name"],
                occurrence_count=row["occurrence_count"],
                frequency=frequency,
                date_range_start=row["date_start"],
                date_range_end=row["date_end"],
                severity=severity,
                context={"frequency_per_day": frequency_per_day},
            )
            patterns.append(pattern)

        self.logger.info(f"Detected {len(patterns)} friction patterns for user {user_id}")
        return patterns

    async def _get_existing_pattern(
        self, user_id: UUID, friction_type: FrictionType, target_id: str
    ) -> Optional[dict]:
        """Check if pattern already exists."""
        query = """
        SELECT id FROM friction_lab.friction_patterns
        WHERE user_id = $1 AND friction_type = $2 AND target_id = $3
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, user_id, friction_type.value, target_id)
        return row

    async def _create_pattern(
        self,
        user_id: UUID,
        friction_type: FrictionType,
        target_id: str,
        target_name: str,
        occurrence_count: int,
        frequency: str,
        severity: float,
        date_start: datetime,
        date_end: datetime,
    ) -> UUID:
        """Create a new pattern record."""
        query = """
        INSERT INTO friction_lab.friction_patterns
        (user_id, friction_type, target_id, target_name, occurrence_count, frequency, severity, date_range_start, date_range_end)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                user_id,
                friction_type.value,
                target_id,
                target_name,
                occurrence_count,
                frequency,
                severity,
                date_start,
                date_end,
            )
        return row["id"]

    async def _update_pattern(
        self,
        pattern_id: UUID,
        occurrence_count: int,
        frequency: str,
        severity: float,
        date_start: datetime,
        date_end: datetime,
    ) -> None:
        """Update an existing pattern."""
        query = """
        UPDATE friction_lab.friction_patterns
        SET occurrence_count = $1, frequency = $2, severity = $3, 
            date_range_start = $4, date_range_end = $5, last_updated = now()
        WHERE id = $6
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, occurrence_count, frequency, severity, date_start, date_end, pattern_id)

    async def generate_proposals(self, pattern: FrictionPattern) -> list[AutomationProposal]:
        """
        Generate automation proposals for a detected friction pattern.

        Uses pattern context and friction type to suggest specific automations.
        """
        proposals = []

        if pattern.friction_type == FrictionType.REPEATED_OVERRIDE:
            # E.g., user keeps manually overriding HVAC schedule
            # Proposal: learn the user's preferred temps and adjust schedule
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "adjust_schedule",
                    "Adapt automation schedule to your preferences",
                    f"You've overridden the {pattern.target_name} {pattern.occurrence_count} times. "
                    f"We can learn your preferred settings and adjust automatically.",
                    "Saves you from manually adjusting every time",
                    0.85,
                    "5-10 min saved per day",
                )
            )

            # Alternative: add smart conditions
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "add_condition",
                    "Add smart conditions to {target_name}",
                    f"Add context-aware conditions (time of day, weather, occupancy) to prevent unwanted triggers.",
                    "Reduces irrelevant automation triggers",
                    0.65,
                    "Fewer manual overrides needed",
                )
            )

        elif pattern.friction_type == FrictionType.POSTPONED_TASK:
            # E.g., user keeps snoozing a daily standup
            # Proposal: reschedule task to more convenient time
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "reschedule_task",
                    "Move {target_name} to a better time",
                    f"You've postponed this {pattern.occurrence_count} times. "
                    f"Let's find a time that works better for you.",
                    "Task will be less disruptive at a better time",
                    0.8,
                    "Less context-switching",
                )
            )

            # Alternative: batch with similar tasks
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "batch_tasks",
                    "Batch {target_name} with related tasks",
                    "Group similar postponed tasks into a single batch.",
                    "Process multiple items in one focused session",
                    0.6,
                    "More efficient task batching",
                )
            )

        elif pattern.friction_type == FrictionType.SKIPPED_HABIT:
            # E.g., user keeps skipping morning meditation
            # Proposal: make habit easier or move to different time
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "simplify_habit",
                    "Make {target_name} easier to do",
                    f"You've skipped this {pattern.occurrence_count} times. "
                    f"We can simplify it or pair it with something you already do daily.",
                    "Lower friction = higher completion",
                    0.75,
                    "Easier habit to maintain",
                )
            )

            # Alternative: reschedule to better time
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "reschedule_habit",
                    "Move {target_name} to a better time",
                    "Find a time in your day when you're more likely to do this habit.",
                    "Aligns with your natural rhythm",
                    0.7,
                    "Better habit completion rate",
                )
            )

            # Reward-based
            proposals.append(
                await self._create_proposal(
                    pattern,
                    "add_reward",
                    "Add a reward for completing {target_name}",
                    "Gamify the habit with streaks, points, or rewards.",
                    "Increases motivation and completion",
                    0.65,
                    "More engaging habit",
                )
            )

        self.logger.info(f"Generated {len(proposals)} proposals for pattern {pattern.id}")
        return proposals

    async def _create_proposal(
        self,
        pattern: FrictionPattern,
        proposal_type: str,
        title: str,
        description: str,
        rationale: str,
        confidence: float,
        estimated_benefit: str,
    ) -> AutomationProposal:
        """Create and store an automation proposal."""
        proposal_id = UUID.__class__.__dict__.get("__new__")(UUID)  # Generate new UUID

        query = """
        INSERT INTO friction_lab.automation_proposals
        (friction_pattern_id, user_id, proposal_type, title, description, rationale, confidence, estimated_benefit)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, created_at
        """

        title_filled = title.replace("{target_name}", pattern.target_name)
        description_filled = description.replace("{target_name}", pattern.target_name)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                UUID(pattern.id),
                pattern.user_id,
                proposal_type,
                title_filled,
                description_filled,
                rationale,
                confidence,
                estimated_benefit,
            )

        return AutomationProposal(
            id=str(row["id"]),
            friction_pattern_id=pattern.id,
            proposal_type=proposal_type,
            title=title_filled,
            description=description_filled,
            rationale=rationale,
            confidence=confidence,
            estimated_benefit=estimated_benefit,
            acceptance_state="pending",
            created_at=row["created_at"],
        )

    async def record_proposal_acceptance(
        self,
        proposal_id: UUID,
        user_id: UUID,
        action: str,  # "accepted", "rejected", "deferred"
        reason: str = None,
    ) -> None:
        """Track user's acceptance/rejection of a proposal."""
        query = """
        INSERT INTO friction_lab.proposal_acceptance_tracking
        (proposal_id, user_id, action, reason)
        VALUES ($1, $2, $3, $4)
        """

        # Also update proposal state if accepted/rejected
        update_query = """
        UPDATE friction_lab.automation_proposals
        SET acceptance_state = $1, accepted_at = CASE WHEN $1 = 'accepted' THEN now() ELSE accepted_at END
        WHERE id = $2
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, proposal_id, user_id, action, reason)
            if action in ["accepted", "rejected"]:
                await conn.execute(update_query, action, proposal_id)

        self.logger.info(f"Recorded {action} for proposal {proposal_id}")

    async def get_user_friction_dashboard(self, user_id: UUID) -> dict:
        """Get comprehensive friction dashboard for a user."""
        # Recent friction events
        events_query = """
        SELECT friction_type, target_name, COUNT(*) as count
        FROM friction_lab.friction_events
        WHERE user_id = $1 AND occurrence_date > now() - interval '7 days'
        GROUP BY friction_type, target_name
        ORDER BY count DESC
        LIMIT 10
        """

        # Active patterns
        patterns_query = """
        SELECT id, friction_type, target_name, occurrence_count, severity, frequency
        FROM friction_lab.friction_patterns
        WHERE user_id = $1 AND last_updated > now() - interval '30 days'
        ORDER BY severity DESC
        """

        # Pending proposals
        proposals_query = """
        SELECT id, title, proposal_type, confidence, estimated_benefit
        FROM friction_lab.automation_proposals
        WHERE user_id = $1 AND acceptance_state = 'pending'
        ORDER BY confidence DESC
        """

        async with self.db.acquire() as conn:
            recent_events = await conn.fetch(events_query, user_id)
            active_patterns = await conn.fetch(patterns_query, user_id)
            pending_proposals = await conn.fetch(proposals_query, user_id)

        return {
            "user_id": str(user_id),
            "recent_friction_events": [dict(r) for r in recent_events],
            "active_patterns": [dict(p) for p in active_patterns],
            "pending_proposals": [dict(p) for p in pending_proposals],
            "summary": {
                "friction_event_count_7d": sum(r["count"] for r in recent_events),
                "pattern_count": len(active_patterns),
                "proposal_count_pending": len(pending_proposals),
            },
        }
