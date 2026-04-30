"""Pydantic models for the Life Navigation System."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Life Model (core financial + life parameters)
# ─────────────────────────────────────────────────────────────────────────────

class LifeModelUpdate(BaseModel):
    birth_year: Optional[int] = None
    target_retirement_age: Optional[int] = None
    current_net_worth: Optional[float] = None
    monthly_income: Optional[float] = None
    monthly_expenses: Optional[float] = None
    monthly_savings_rate: Optional[float] = None   # override if set; else income-expenses
    investment_return_pct: Optional[float] = None  # annual expected return (e.g. 0.07)
    passive_income_monthly: Optional[float] = None # rental, dividends, etc.
    target_fi_monthly_expense: Optional[float] = None  # FI target spending
    withdrawal_rate: Optional[float] = None        # SWR default 0.04
    income_growth_pct: Optional[float] = None      # annual income growth e.g. 0.03
    notes: Optional[str] = None


class LifeModel(BaseModel):
    id: uuid.UUID
    user_id: str
    birth_year: int
    target_retirement_age: int
    current_net_worth: float
    monthly_income: float
    monthly_expenses: float
    monthly_savings_rate: Optional[float] = None
    investment_return_pct: float
    passive_income_monthly: float
    target_fi_monthly_expense: float
    withdrawal_rate: float
    income_growth_pct: float
    notes: Optional[str] = None
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Goals
# ─────────────────────────────────────────────────────────────────────────────

LIFE_AREAS = {"career", "health", "finance", "relationships", "learning", "leisure", "other"}
GOAL_STATUSES = {"active", "completed", "abandoned", "paused"}


class GoalCreate(BaseModel):
    title: str
    description: str = ""
    life_area: str = "other"  # career, health, finance, relationships, learning, leisure, other
    target_date: Optional[date] = None
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    milestones: list[dict[str, Any]] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    life_area: Optional[str] = None
    target_date: Optional[date] = None
    status: Optional[str] = None
    progress_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    milestones: Optional[list[dict[str, Any]]] = None


class Goal(GoalCreate):
    id: uuid.UUID
    user_id: str
    status: str = "active"
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Weekly Reviews
# ─────────────────────────────────────────────────────────────────────────────

class WeeklyReviewCreate(BaseModel):
    week_start: date
    accomplishments: str = ""
    challenges: str = ""
    learnings: str = ""
    next_week_focus: str = ""
    energy_level: int = Field(default=5, ge=1, le=10)
    mood: int = Field(default=5, ge=1, le=10)


class WeeklyReview(WeeklyReviewCreate):
    id: uuid.UUID
    user_id: str
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Health Metrics
# ─────────────────────────────────────────────────────────────────────────────

class HealthMetricCreate(BaseModel):
    measured_at: Optional[datetime] = None
    weight_kg: Optional[float] = None
    resting_hr: Optional[int] = None
    vo2max_estimated: Optional[float] = None
    sleep_hours_avg: Optional[float] = None
    training_hours_week: Optional[float] = None
    source: str = "manual"  # manual, intervals_icu


class HealthMetric(HealthMetricCreate):
    id: uuid.UUID
    user_id: str
    measured_at: datetime
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Career Milestones
# ─────────────────────────────────────────────────────────────────────────────

CAREER_STATUSES = {"planned", "achieved", "missed", "in_progress"}


class CareerMilestoneCreate(BaseModel):
    title: str
    description: str = ""
    target_date: Optional[date] = None
    impact_score: int = Field(default=5, ge=1, le=10)


class CareerMilestoneUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_date: Optional[date] = None
    achieved_at: Optional[date] = None
    status: Optional[str] = None
    impact_score: Optional[int] = Field(default=None, ge=1, le=10)


class CareerMilestone(CareerMilestoneCreate):
    id: uuid.UUID
    user_id: str
    status: str = "planned"
    achieved_at: Optional[date] = None
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo Simulation
# ─────────────────────────────────────────────────────────────────────────────

class SimulationParams(BaseModel):
    scenario_name: str = "baseline"
    # Override life model values for what-if scenarios
    current_net_worth: Optional[float] = None
    monthly_income: Optional[float] = None
    monthly_expenses: Optional[float] = None
    investment_return_mean: Optional[float] = None  # annual (e.g. 0.07)
    investment_return_std: Optional[float] = None   # annual volatility (e.g. 0.15)
    inflation_mean: Optional[float] = None
    inflation_std: Optional[float] = None
    income_growth_pct: Optional[float] = None
    withdrawal_rate: Optional[float] = None
    target_fi_monthly_expense: Optional[float] = None
    project_years: int = Field(default=40, ge=5, le=60)
    n_simulations: Optional[int] = Field(default=None, ge=100, le=5000)


class YearlyProjection(BaseModel):
    year: int
    age: int
    p10: float
    p50: float
    p90: float


class SimulationResult(BaseModel):
    id: uuid.UUID
    user_id: str
    scenario_name: str
    parameters: dict[str, Any]
    trajectory: list[YearlyProjection]        # year-by-year p10/p50/p90
    fi_age_p10: Optional[float] = None        # age at FI in pessimistic scenario
    fi_age_p50: Optional[float] = None        # age at FI in median scenario
    fi_age_p90: Optional[float] = None        # age at FI in optimistic scenario
    fi_net_worth_target: float                # net_worth needed for FI
    current_net_worth: float
    run_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Opportunities
# ─────────────────────────────────────────────────────────────────────────────

OPPORTUNITY_CATEGORIES = {"job", "travel", "investment", "learning", "health", "other"}


class OpportunityCreate(BaseModel):
    title: str
    description: str = ""
    category: str = "other"
    url: Optional[str] = None
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_at: Optional[datetime] = None


class Opportunity(OpportunityCreate):
    id: uuid.UUID
    user_id: str
    source: str = "manual"  # manual, web_search
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Cook Planner — Phase 3
# ─────────────────────────────────────────────────────────────────────────────

class MealPlanCreate(BaseModel):
    plan_date: date
    breakfast: str = ""
    lunch: str = ""
    dinner: str = ""
    snacks: str = ""
    notes: str = ""
    calories_target: Optional[int] = None
    protein_g_target: Optional[float] = None
    carbs_g_target: Optional[float] = None
    fat_g_target: Optional[float] = None


class MealPlan(MealPlanCreate):
    id: uuid.UUID
    user_id: str
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Multi-objective optimizer — Phase 4
# ─────────────────────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    career_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    finance_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    health_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    relationships_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    time_horizon_years: int = Field(default=5, ge=1, le=30)


class ActionRecommendation(BaseModel):
    title: str
    description: str
    life_area: str
    priority_score: float = Field(ge=0.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)
    effort_score: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=low effort, 1=high
    source: str = "optimizer"  # goal, finance, health, career


class OptimizeResult(BaseModel):
    recommendations: list[ActionRecommendation]
    dominant_objective: str       # life area with highest weight
    trade_off_summary: str        # human-readable tradeoff description
    fi_impact_years: Optional[float] = None   # how much FI date changes if finance prioritised
    weights_used: dict[str, float] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Opportunity refresh result — Phase 3
# ─────────────────────────────────────────────────────────────────────────────

class OpportunityRefreshResult(BaseModel):
    added: int = 0
    skipped: int = 0
    categories_searched: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# intervals.icu sync result — Phase 3
# ─────────────────────────────────────────────────────────────────────────────

class IntervalsSyncResult(BaseModel):
    synced: int = 0
    latest_activity_date: Optional[date] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class LifeNavDashboard(BaseModel):
    # Financial snapshot
    current_net_worth: Optional[float] = None
    fi_target_net_worth: Optional[float] = None
    fi_progress_pct: Optional[float] = None
    fi_age_p50: Optional[float] = None        # median FI age from latest simulation
    years_to_fi_p50: Optional[float] = None
    monthly_savings: Optional[float] = None

    # Goals summary
    active_goals: int = 0
    completed_goals: int = 0
    goals_by_area: dict[str, int] = Field(default_factory=dict)

    # Health snapshot
    latest_vo2max: Optional[float] = None
    latest_weight_kg: Optional[float] = None
    training_hours_this_week: Optional[float] = None

    # Reviews
    last_weekly_review: Optional[date] = None
    days_since_last_review: Optional[int] = None

    # Career
    planned_milestones: int = 0
    achieved_milestones: int = 0

    # Opportunities
    opportunities_this_week: list[Opportunity] = Field(default_factory=list)
