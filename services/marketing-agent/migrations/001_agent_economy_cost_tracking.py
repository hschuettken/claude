"""
Agent Economy integration: Token cost tracking and ROI calculation.
Task 194: Marketing agent has token budget, tracks cost per post, optimizes LLM usage.

Revision ID: 001_agent_economy_cost_tracking
Revises: (base)
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "001_agent_economy_cost_tracking"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create marketing_token_costs table
    op.create_table(
        "marketing_token_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feature", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_token_costs_draft_id", "marketing_token_costs", ["draft_id"])
    op.create_index("idx_token_costs_date", "marketing_token_costs", ["created_at"])
    op.create_index("idx_token_costs_feature", "marketing_token_costs", ["feature"])

    # Create marketing_draft_costs table
    op.create_table(
        "marketing_draft_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=True),
        sa.Column("pillar", sa.String(length=100), nullable=True),
        sa.Column("discovery_cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("drafting_cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("review_cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("publishing_cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("estimated_reach", sa.Integer(), nullable=True),
        sa.Column("actual_views", sa.Integer(), nullable=True),
        sa.Column("actual_engagement_score", sa.Float(), nullable=True),
        sa.Column("engagement_value_usd", sa.DECIMAL(precision=10, scale=6), nullable=True),
        sa.Column("roi_percent", sa.Float(), nullable=True),
        sa.Column("cost_per_engagement_usd", sa.DECIMAL(precision=10, scale=6), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_draft_costs_draft_id", "marketing_draft_costs", ["draft_id"])
    op.create_index("idx_draft_costs_published_date", "marketing_draft_costs", ["published_at"])

    # Create marketing_token_budgets table
    op.create_table(
        "marketing_token_budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("monthly_budget_usd", sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column("daily_budget_usd", sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column("month_start_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("current_month_spent_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("current_day_spent_usd", sa.DECIMAL(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("alert_threshold_pct", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("last_alert_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create marketing_model_optimizations table
    op.create_table(
        "marketing_model_optimizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feature", sa.String(length=100), nullable=False),
        sa.Column("default_model", sa.String(length=100), nullable=False),
        sa.Column("optimized_model", sa.String(length=100), nullable=False),
        sa.Column("cost_reduction_percent", sa.Float(), nullable=False),
        sa.Column("quality_trade_off", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("marketing_model_optimizations")
    op.drop_table("marketing_token_budgets")
    op.drop_table("marketing_draft_costs")
    op.drop_table("marketing_token_costs")
