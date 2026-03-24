"""
Cost tracking and ROI calculation for marketing content creation.
Integrates with Agent Economy to track token budget and optimize LLM usage.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models_cost_tracking import (
    TokenCostEntry,
    DraftCostSummary,
    TokenBudgetWorkspace,
    LLMModelOptimization,
    ContentStageEnum,
)

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks token costs and ROI for marketing content creation."""

    # Model pricing (USD per 1K tokens)
    MODEL_PRICES = {
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-opus": {"input": 0.015, "output": 0.075},
        "claude-sonnet": {"input": 0.003, "output": 0.015},
        "claude-haiku": {"input": 0.00025, "output": 0.00125},
        "mistral-large": {"input": 0.002, "output": 0.006},
        "ollama-base": {"input": 0.0, "output": 0.0},  # Local, no cost
    }

    @staticmethod
    def calculate_cost(
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Calculate LLM call cost in USD."""
        if model not in CostTracker.MODEL_PRICES:
            logger.warning(f"Unknown model: {model}, defaulting to gpt-4o-mini pricing")
            model = "gpt-4o-mini"

        pricing = CostTracker.MODEL_PRICES[model]
        input_cost = (prompt_tokens / 1000.0) * pricing["input"]
        output_cost = (completion_tokens / 1000.0) * pricing["output"]
        return input_cost + output_cost

    @staticmethod
    async def log_token_usage(
        db: AsyncSession,
        draft_id: UUID | None,
        feature: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        stage: str = "drafting",
        duration_seconds: int | None = None,
    ) -> TokenCostEntry:
        """Log a token usage event."""
        cost_usd = CostTracker.calculate_cost(model, prompt_tokens, completion_tokens)

        entry = TokenCostEntry(
            draft_id=draft_id,
            feature=feature,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=Decimal(str(cost_usd)),
            stage=stage,
            duration_seconds=duration_seconds,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

    @staticmethod
    async def get_draft_cost_summary(
        db: AsyncSession,
        draft_id: UUID,
    ) -> DraftCostSummary | None:
        """Get cost summary for a specific draft."""
        stmt = select(DraftCostSummary).where(DraftCostSummary.draft_id == draft_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def update_draft_costs(
        db: AsyncSession,
        draft_id: UUID,
        title: str,
        topic: str | None = None,
        pillar: str | None = None,
    ) -> DraftCostSummary:
        """Calculate and update cost summary for a draft from token log entries."""
        # Get all token cost entries for this draft
        stmt = select(TokenCostEntry).where(TokenCostEntry.draft_id == draft_id)
        result = await db.execute(stmt)
        entries = result.scalars().all()

        # Aggregate by stage
        stage_costs = {stage.value: Decimal("0") for stage in ContentStageEnum}
        for entry in entries:
            stage_costs[entry.stage] += entry.cost_usd

        # Check if summary exists
        stmt = select(DraftCostSummary).where(DraftCostSummary.draft_id == draft_id)
        result = await db.execute(stmt)
        summary = result.scalars().first()

        if summary is None:
            summary = DraftCostSummary(
                draft_id=draft_id,
                title=title,
                topic=topic,
                pillar=pillar,
            )

        # Update costs
        summary.discovery_cost_usd = stage_costs.get(ContentStageEnum.DISCOVERY.value, Decimal("0"))
        summary.drafting_cost_usd = stage_costs.get(ContentStageEnum.DRAFTING.value, Decimal("0"))
        summary.review_cost_usd = stage_costs.get(ContentStageEnum.REVIEW.value, Decimal("0"))
        summary.publishing_cost_usd = stage_costs.get(ContentStageEnum.PUBLISHING.value, Decimal("0"))
        summary.total_cost_usd = sum(stage_costs.values())
        summary.updated_at = datetime.utcnow()

        db.add(summary)
        await db.commit()
        await db.refresh(summary)
        return summary

    @staticmethod
    async def calculate_roi(
        db: AsyncSession,
        draft_id: UUID,
        actual_views: int,
        engagement_score: float,  # likes + comments + shares
    ) -> DraftCostSummary:
        """Calculate ROI for a published post."""
        summary = await CostTracker.get_draft_cost_summary(db, draft_id)
        if not summary:
            raise ValueError(f"No cost summary found for draft {draft_id}")

        summary.actual_views = actual_views
        summary.actual_engagement_score = engagement_score

        # Calculate engagement value (industry standard: $0.50-$2.00 per engagement unit)
        engagement_value = Decimal(str(float(engagement_score) * 1.0))  # $1.00 per engagement unit
        summary.engagement_value_usd = engagement_value

        # Calculate ROI: (engagement_value - cost) / cost * 100
        if summary.total_cost_usd > 0:
            roi = ((engagement_value - summary.total_cost_usd) / summary.total_cost_usd) * 100
            summary.roi_percent = float(roi)
            summary.cost_per_engagement_usd = summary.total_cost_usd / engagement_score if engagement_score > 0 else None
        else:
            summary.roi_percent = float("inf")
            summary.cost_per_engagement_usd = Decimal("0")

        summary.updated_at = datetime.utcnow()
        db.add(summary)
        await db.commit()
        await db.refresh(summary)
        return summary

    @staticmethod
    async def check_budget_status(
        db: AsyncSession,
        workspace_id: UUID,
    ) -> dict:
        """Check current budget usage and alert status."""
        stmt = select(TokenBudgetWorkspace).where(
            TokenBudgetWorkspace.workspace_id == workspace_id
        )
        result = await db.execute(stmt)
        budget = result.scalars().first()

        if not budget:
            return {
                "workspace_id": workspace_id,
                "status": "no_budget_configured",
                "daily_spent": 0.0,
                "monthly_spent": 0.0,
            }

        # Check if we're in a new day/month
        now = datetime.utcnow()
        day_ago = now - timedelta(days=1)
        month_ago = now - timedelta(days=30)

        # Reset daily if needed
        if budget.month_start_date.date() != now.date():
            budget.current_day_spent_usd = Decimal("0")

        # Reset monthly if needed
        if (now - budget.month_start_date).days >= 30:
            budget.month_start_date = now
            budget.current_month_spent_usd = Decimal("0")

        # Calculate thresholds
        daily_threshold = (
            float(budget.daily_budget_usd) * budget.alert_threshold_pct
            if budget.daily_budget_usd
            else None
        )
        monthly_threshold = (
            float(budget.monthly_budget_usd) * budget.alert_threshold_pct
            if budget.monthly_budget_usd
            else None
        )

        return {
            "workspace_id": workspace_id,
            "status": "ok",
            "daily_budget": float(budget.daily_budget_usd) if budget.daily_budget_usd else None,
            "monthly_budget": float(budget.monthly_budget_usd) if budget.monthly_budget_usd else None,
            "daily_spent": float(budget.current_day_spent_usd),
            "monthly_spent": float(budget.current_month_spent_usd),
            "daily_threshold": daily_threshold,
            "monthly_threshold": monthly_threshold,
            "daily_alert": daily_threshold and float(budget.current_day_spent_usd) >= daily_threshold,
            "monthly_alert": monthly_threshold and float(budget.current_month_spent_usd) >= monthly_threshold,
        }

    @staticmethod
    async def get_cost_dashboard_data(
        db: AsyncSession,
        workspace_id: UUID,
        days: int = 30,
    ) -> dict:
        """Get comprehensive cost dashboard data."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Total cost by feature
        stmt = select(
            TokenCostEntry.feature,
            func.sum(TokenCostEntry.cost_usd).label("total_cost"),
            func.count(TokenCostEntry.id).label("call_count"),
        ).where(
            and_(
                TokenCostEntry.draft_id.isnot(None),
                TokenCostEntry.created_at >= cutoff_date,
            )
        ).group_by(TokenCostEntry.feature)
        result = await db.execute(stmt)
        cost_by_feature = [
            {"feature": row[0], "cost": float(row[1]), "calls": row[2]} for row in result
        ]

        # Total cost by model
        stmt = select(
            TokenCostEntry.model,
            func.sum(TokenCostEntry.cost_usd).label("total_cost"),
            func.count(TokenCostEntry.id).label("call_count"),
        ).where(TokenCostEntry.created_at >= cutoff_date).group_by(TokenCostEntry.model)
        result = await db.execute(stmt)
        cost_by_model = [
            {"model": row[0], "cost": float(row[1]), "calls": row[2]} for row in result
        ]

        # Published post statistics
        stmt = select(
            func.count(DraftCostSummary.id).label("posts_count"),
            func.sum(DraftCostSummary.total_cost_usd).label("total_cost"),
            func.avg(DraftCostSummary.roi_percent).label("avg_roi"),
            func.avg(DraftCostSummary.engagement_value_usd).label("avg_engagement_value"),
        ).where(
            and_(
                DraftCostSummary.published_at.isnot(None),
                DraftCostSummary.published_at >= cutoff_date,
            )
        )
        result = await db.execute(stmt)
        row = result.first()
        
        post_stats = {
            "posts_published": row[0] or 0,
            "total_cost": float(row[1] or 0),
            "avg_roi_percent": float(row[2] or 0),
            "avg_engagement_value": float(row[3] or 0),
        }

        # Budget status
        budget_status = await CostTracker.check_budget_status(db, workspace_id)

        return {
            "period_days": days,
            "cost_by_feature": cost_by_feature,
            "cost_by_model": cost_by_model,
            "post_statistics": post_stats,
            "budget_status": budget_status,
        }

    @staticmethod
    async def recommend_model_optimization(
        db: AsyncSession,
        feature: str,
        current_model: str,
    ) -> dict | None:
        """Recommend cost-optimized model for a feature."""
        # Check if optimization already exists
        stmt = select(LLMModelOptimization).where(
            and_(
                LLMModelOptimization.feature == feature,
                LLMModelOptimization.default_model == current_model,
                LLMModelOptimization.enabled == 1,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalars().first()

        if existing:
            return {
                "feature": existing.feature,
                "current_model": existing.default_model,
                "optimized_model": existing.optimized_model,
                "cost_reduction_percent": existing.cost_reduction_percent,
                "quality_trade_off": existing.quality_trade_off,
                "enabled": bool(existing.enabled),
            }

        # No specific optimization found
        return None
