"""
Cost tracking models for Agent Economy integration.
Tracks token costs per content creation task and ROI calculations.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Index, DECIMAL
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ContentStageEnum(str, Enum):
    """Stages of content creation."""
    DISCOVERY = "discovery"
    DRAFTING = "drafting"
    REVIEW = "review"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


class TokenCostEntry(Base):
    """Tracks token usage and cost for each content creation task."""
    __tablename__ = "marketing_token_costs"
    __table_args__ = (
        Index("idx_token_costs_draft_id", "draft_id"),
        Index("idx_token_costs_date", "created_at"),
        Index("idx_token_costs_feature", "feature"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    draft_id = Column(PG_UUID(as_uuid=True), nullable=True, comment="Links to blog_posts.id")
    feature = Column(String(100), nullable=False, comment="Feature name: topic_scoring, draft_generation, image_prompt, etc.")
    model = Column(String(100), nullable=False, comment="Model name: gpt-4, claude-opus, etc.")
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0, comment="Total cost in USD")
    stage = Column(String(50), nullable=False, comment="Content stage: discovery, drafting, review, publishing")
    duration_seconds = Column(Integer, nullable=True, comment="How long the LLM call took")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.prompt_tokens + self.completion_tokens


class DraftCostSummary(Base):
    """Aggregated cost per draft/post."""
    __tablename__ = "marketing_draft_costs"
    __table_args__ = (
        Index("idx_draft_costs_draft_id", "draft_id"),
        Index("idx_draft_costs_published_date", "published_at"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    draft_id = Column(PG_UUID(as_uuid=True), nullable=False, unique=True, comment="Links to blog_posts.id")
    title = Column(String(500), nullable=False)
    topic = Column(String(200), nullable=True)
    pillar = Column(String(100), nullable=True)
    
    # Cost breakdown
    discovery_cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0, comment="Cost of topic discovery/signals")
    drafting_cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0, comment="Cost of draft generation")
    review_cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0, comment="Cost of review/refinement")
    publishing_cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0, comment="Cost of final publishing prep")
    total_cost_usd = Column(DECIMAL(10, 6), nullable=False, default=0)
    
    # Engagement metrics
    estimated_reach = Column(Integer, nullable=True, comment="Projected audience reach")
    actual_views = Column(Integer, nullable=True, comment="Actual page views")
    actual_engagement_score = Column(Float, nullable=True, comment="Engagement: likes + comments + shares")
    engagement_value_usd = Column(DECIMAL(10, 6), nullable=True, comment="Estimated value of engagement (cost per view)")
    
    # ROI
    roi_percent = Column(Float, nullable=True, comment="ROI: (engagement_value - cost) / cost * 100")
    cost_per_engagement_usd = Column(DECIMAL(10, 6), nullable=True, comment="Cost per engagement unit")
    
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")


class TokenBudgetWorkspace(Base):
    """Token budget allocation per workspace/marketing-agent."""
    __tablename__ = "marketing_token_budgets"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    workspace_id = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    
    # Budget limits
    monthly_budget_usd = Column(DECIMAL(10, 2), nullable=True, comment="Monthly spend limit in USD")
    daily_budget_usd = Column(DECIMAL(10, 2), nullable=True, comment="Daily spend limit in USD")
    
    # Current usage
    month_start_date = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    current_month_spent_usd = Column(DECIMAL(10, 6), nullable=False, default=0)
    current_day_spent_usd = Column(DECIMAL(10, 6), nullable=False, default=0)
    
    # Alerts
    alert_threshold_pct = Column(Float, nullable=False, default=0.8, comment="Alert when threshold% of budget used")
    last_alert_sent_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")


class LLMModelOptimization(Base):
    """Tracks model optimization decisions for cost reduction."""
    __tablename__ = "marketing_model_optimizations"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    feature = Column(String(100), nullable=False, comment="Feature: topic_scoring, draft_gen, etc.")
    default_model = Column(String(100), nullable=False, comment="Original model")
    optimized_model = Column(String(100), nullable=False, comment="Cost-optimized alternative")
    cost_reduction_percent = Column(Float, nullable=False, comment="Estimated % cost reduction")
    quality_trade_off = Column(String(500), nullable=True, comment="Any quality trade-offs")
    enabled = Column(Integer, nullable=False, default=0, comment="1 = use optimized model, 0 = use original")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
