"""
API endpoints for marketing agent cost tracking and ROI reporting.
Provides cost dashboard, budget status, and optimization recommendations.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cost_tracking import CostTracker
from database import get_db

router = APIRouter(prefix="/api/v1/marketing", tags=["marketing-cost-tracking"])


# ============= Pydantic Models =============

class TokenCostLog(BaseModel):
    """Request to log token usage."""
    draft_id: UUID | None = None
    feature: str  # topic_scoring, draft_generation, image_prompt, etc.
    model: str  # gpt-4o, claude-opus, etc.
    prompt_tokens: int
    completion_tokens: int
    stage: str = "drafting"  # discovery, drafting, review, publishing
    duration_seconds: int | None = None


class DraftCostUpdate(BaseModel):
    """Request to update cost summary for a draft."""
    draft_id: UUID
    title: str
    topic: str | None = None
    pillar: str | None = None


class EngagementData(BaseModel):
    """Engagement metrics for ROI calculation."""
    draft_id: UUID
    actual_views: int
    engagement_score: float  # likes + comments + shares


class CostDashboardResponse(BaseModel):
    """Cost dashboard data response."""
    period_days: int
    cost_by_feature: list
    cost_by_model: list
    post_statistics: dict
    budget_status: dict


class BudgetStatusResponse(BaseModel):
    """Budget status response."""
    workspace_id: UUID
    status: str
    daily_budget: float | None
    monthly_budget: float | None
    daily_spent: float
    monthly_spent: float
    daily_alert: bool
    monthly_alert: bool


class ModelOptimizationRecommendation(BaseModel):
    """Model optimization recommendation."""
    feature: str
    current_model: str
    optimized_model: str
    cost_reduction_percent: float
    quality_trade_off: str | None
    enabled: bool


# ============= Endpoints =============

@router.post("/token-usage/log")
async def log_token_usage(
    log: TokenCostLog,
    db: AsyncSession = Depends(get_db),
):
    """Log token usage for a marketing content creation task."""
    entry = await CostTracker.log_token_usage(
        db=db,
        draft_id=log.draft_id,
        feature=log.feature,
        model=log.model,
        prompt_tokens=log.prompt_tokens,
        completion_tokens=log.completion_tokens,
        stage=log.stage,
        duration_seconds=log.duration_seconds,
    )
    return {
        "id": str(entry.id),
        "cost_usd": float(entry.cost_usd),
        "total_tokens": entry.total_tokens(),
    }


@router.post("/drafts/update-costs")
async def update_draft_costs(
    update: DraftCostUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update cost summary for a draft."""
    summary = await CostTracker.update_draft_costs(
        db=db,
        draft_id=update.draft_id,
        title=update.title,
        topic=update.topic,
        pillar=update.pillar,
    )
    return {
        "draft_id": str(summary.draft_id),
        "total_cost_usd": float(summary.total_cost_usd),
        "discovery_cost": float(summary.discovery_cost_usd),
        "drafting_cost": float(summary.drafting_cost_usd),
        "review_cost": float(summary.review_cost_usd),
        "publishing_cost": float(summary.publishing_cost_usd),
    }


@router.post("/drafts/calculate-roi")
async def calculate_roi(
    engagement: EngagementData,
    db: AsyncSession = Depends(get_db),
):
    """Calculate ROI for a published post."""
    summary = await CostTracker.calculate_roi(
        db=db,
        draft_id=engagement.draft_id,
        actual_views=engagement.actual_views,
        engagement_score=engagement.engagement_score,
    )
    return {
        "draft_id": str(summary.draft_id),
        "total_cost_usd": float(summary.total_cost_usd),
        "actual_views": summary.actual_views,
        "engagement_score": summary.actual_engagement_score,
        "engagement_value_usd": float(summary.engagement_value_usd) if summary.engagement_value_usd else 0,
        "roi_percent": summary.roi_percent,
        "cost_per_engagement_usd": float(summary.cost_per_engagement_usd) if summary.cost_per_engagement_usd else 0,
    }


@router.get("/budget/status")
async def get_budget_status(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BudgetStatusResponse:
    """Get current budget status for a workspace."""
    status = await CostTracker.check_budget_status(db, workspace_id)
    return BudgetStatusResponse(**status)


@router.get("/cost-dashboard")
async def get_cost_dashboard(
    workspace_id: UUID = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> CostDashboardResponse:
    """Get cost dashboard data for the past N days."""
    data = await CostTracker.get_cost_dashboard_data(db, workspace_id, days)
    return CostDashboardResponse(**data)


@router.get("/model-optimization/recommend")
async def recommend_model_optimization(
    feature: str = Query(...),
    current_model: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get model optimization recommendation for a feature."""
    recommendation = await CostTracker.recommend_model_optimization(
        db=db,
        feature=feature,
        current_model=current_model,
    )
    if recommendation:
        return recommendation
    else:
        return {
            "feature": feature,
            "current_model": current_model,
            "recommendation": "No optimization configured. Consider using a cheaper model if quality allows.",
        }


@router.post("/cost-analysis")
async def generate_cost_analysis(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Generate comprehensive cost analysis and optimization recommendations."""
    dashboard = await CostTracker.get_cost_dashboard_data(db, workspace_id, 30)
    
    # Build recommendations
    recommendations = []
    
    # Check if certain features are unusually expensive
    for feature_cost in dashboard["cost_by_feature"]:
        if feature_cost["cost"] > 100:  # Arbitrary threshold for demonstration
            recommendations.append({
                "type": "high_cost_feature",
                "feature": feature_cost["feature"],
                "current_cost": feature_cost["cost"],
                "suggestion": f"Consider using a cheaper model for {feature_cost['feature']}",
            })
    
    # Check budget status
    budget = dashboard["budget_status"]
    if budget["status"] != "no_budget_configured":
        if budget["daily_alert"]:
            recommendations.append({
                "type": "budget_alert",
                "level": "daily",
                "current_usage": budget["daily_spent"],
                "budget": budget["daily_budget"],
                "suggestion": "Daily spending approaching budget. Consider pausing content creation.",
            })
        if budget["monthly_alert"]:
            recommendations.append({
                "type": "budget_alert",
                "level": "monthly",
                "current_usage": budget["monthly_spent"],
                "budget": budget["monthly_budget"],
                "suggestion": "Monthly spending approaching budget. Plan for next month.",
            })
    
    # Check post ROI
    post_stats = dashboard["post_statistics"]
    if post_stats["avg_roi_percent"] and post_stats["avg_roi_percent"] < -50:
        recommendations.append({
            "type": "low_roi",
            "avg_roi": post_stats["avg_roi_percent"],
            "suggestion": "Recent posts have low ROI. Review content strategy and engagement metrics.",
        })
    
    return {
        "workspace_id": workspace_id,
        "analysis_date": "2026-03-24",
        "dashboard": dashboard,
        "recommendations": recommendations,
        "summary": {
            "total_cost_30d": dashboard["post_statistics"]["total_cost"],
            "posts_published": dashboard["post_statistics"]["posts_published"],
            "avg_cost_per_post": (
                dashboard["post_statistics"]["total_cost"] / dashboard["post_statistics"]["posts_published"]
                if dashboard["post_statistics"]["posts_published"] > 0
                else 0
            ),
        }
    }
