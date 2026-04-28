"""Life Navigation System — FastAPI application.

Port: 8243

Provides:
  Life Model     — financial + life parameters (net worth, income, expenses, FI target)
  Goals          — goal tracking with progress, milestones, life areas
  Weekly Reviews — structured weekly reflection
  Health Metrics — fitness tracking (weight, HR, VO2max, training hours)
  Career         — career milestone planning and tracking
  Simulation     — Monte Carlo net worth trajectory + FI age projection
  Opportunities  — manual + auto "Opportunities This Week" card

NATS subjects published:
  life.goal.completed    — when a goal is marked completed
  life.simulation.run    — when a Monte Carlo simulation completes
  life.review.created    — when a weekly review is submitted
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from . import monte_carlo as mc
from .config import settings
from .models import (
    CareerMilestone,
    CareerMilestoneCreate,
    CareerMilestoneUpdate,
    Goal,
    GoalCreate,
    GoalUpdate,
    HealthMetric,
    HealthMetricCreate,
    LifeModel,
    LifeModelUpdate,
    LifeNavDashboard,
    Opportunity,
    OpportunityCreate,
    SimulationParams,
    SimulationResult,
    WeeklyReview,
    WeeklyReviewCreate,
    YearlyProjection,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_nats: Optional[Any] = None
_background_tasks: list[asyncio.Task] = []


# ─────────────────────────────────────────────────────────────────────────────
# NATS
# ─────────────────────────────────────────────────────────────────────────────

async def _start_nats() -> None:
    global _nats
    try:
        from shared.nats_client import NatsPublisher  # type: ignore[import]
        _nats = NatsPublisher(url=settings.nats_url)
        await _nats.connect()
        logger.info("life_nav nats_connected")
    except Exception as exc:
        logger.warning("life_nav nats_unavailable error=%s", exc)
        _nats = None


async def _publish_nats(subject: str, payload: dict[str, Any]) -> None:
    if _nats is None:
        return
    try:
        await _nats.publish(subject, json.dumps(payload).encode())
    except Exception as exc:
        logger.debug("life_nav nats_publish_failed subject=%s error=%s", subject, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    await _start_nats()
    _background_tasks.append(asyncio.create_task(_register_with_oracle()))
    logger.info("life_nav_started port=%d", settings.port)
    yield
    for t in _background_tasks:
        t.cancel()
    if _nats is not None:
        await _nats.close()
    await db.close_pool()
    logger.info("life_nav_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Life Navigation System",
    description=(
        "Personal life model, goal tracking, Monte Carlo financial simulation, "
        "health metrics, career milestones, and opportunities radar."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    pool_ok = db.get_pool() is not None
    return {
        "status": "ok" if pool_ok else "degraded",
        "db": "connected" if pool_ok else "unavailable",
        "nats": "connected" if (_nats and getattr(_nats, "connected", False)) else "disconnected",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _uid() -> str:
    return settings.default_user


def _row_to_life_model(row: Any) -> LifeModel:
    return LifeModel(
        id=row["id"],
        user_id=row["user_id"],
        birth_year=row["birth_year"],
        target_retirement_age=row["target_retirement_age"],
        current_net_worth=float(row["current_net_worth"]),
        monthly_income=float(row["monthly_income"]),
        monthly_expenses=float(row["monthly_expenses"]),
        monthly_savings_rate=float(row["monthly_savings_rate"]) if row["monthly_savings_rate"] is not None else None,
        investment_return_pct=float(row["investment_return_pct"]),
        passive_income_monthly=float(row["passive_income_monthly"]),
        target_fi_monthly_expense=float(row["target_fi_monthly_expense"]),
        withdrawal_rate=float(row["withdrawal_rate"]),
        income_growth_pct=float(row["income_growth_pct"]),
        notes=row["notes"],
        updated_at=row["updated_at"],
    )


def _row_to_goal(row: Any) -> Goal:
    return Goal(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"] or "",
        life_area=row["life_area"],
        target_date=row["target_date"],
        status=row["status"],
        progress_pct=float(row["progress_pct"]),
        milestones=row["milestones"] if isinstance(row["milestones"], list) else (
            json.loads(row["milestones"]) if row["milestones"] else []
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_review(row: Any) -> WeeklyReview:
    return WeeklyReview(
        id=row["id"],
        user_id=row["user_id"],
        week_start=row["week_start"],
        accomplishments=row["accomplishments"] or "",
        challenges=row["challenges"] or "",
        learnings=row["learnings"] or "",
        next_week_focus=row["next_week_focus"] or "",
        energy_level=row["energy_level"],
        mood=row["mood"],
        created_at=row["created_at"],
    )


def _row_to_health_metric(row: Any) -> HealthMetric:
    return HealthMetric(
        id=row["id"],
        user_id=row["user_id"],
        measured_at=row["measured_at"],
        weight_kg=float(row["weight_kg"]) if row["weight_kg"] is not None else None,
        resting_hr=row["resting_hr"],
        vo2max_estimated=float(row["vo2max_estimated"]) if row["vo2max_estimated"] is not None else None,
        sleep_hours_avg=float(row["sleep_hours_avg"]) if row["sleep_hours_avg"] is not None else None,
        training_hours_week=float(row["training_hours_week"]) if row["training_hours_week"] is not None else None,
        source=row["source"],
        created_at=row["created_at"],
    )


def _row_to_career_milestone(row: Any) -> CareerMilestone:
    return CareerMilestone(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"] or "",
        target_date=row["target_date"],
        achieved_at=row["achieved_at"],
        status=row["status"],
        impact_score=row["impact_score"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_opportunity(row: Any) -> Opportunity:
    return Opportunity(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"] or "",
        category=row["category"],
        url=row["url"],
        relevance_score=float(row["relevance_score"]),
        source=row["source"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


def _row_to_simulation(row: Any) -> SimulationResult:
    trajectory_raw = row["trajectory"]
    if isinstance(trajectory_raw, str):
        trajectory_raw = json.loads(trajectory_raw)
    trajectory = [YearlyProjection(**yp) for yp in trajectory_raw]
    return SimulationResult(
        id=row["id"],
        user_id=row["user_id"],
        scenario_name=row["scenario_name"],
        parameters=row["parameters"] if isinstance(row["parameters"], dict) else json.loads(row["parameters"]),
        trajectory=trajectory,
        fi_age_p10=float(row["fi_age_p10"]) if row["fi_age_p10"] is not None else None,
        fi_age_p50=float(row["fi_age_p50"]) if row["fi_age_p50"] is not None else None,
        fi_age_p90=float(row["fi_age_p90"]) if row["fi_age_p90"] is not None else None,
        fi_net_worth_target=float(row["fi_net_worth_target"]),
        current_net_worth=float(row["current_net_worth"]),
        run_at=row["run_at"],
    )


async def _get_life_model_row() -> Optional[Any]:
    return await db.fetchrow(
        "SELECT * FROM ln_life_model WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
        _uid(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Life Model
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/model", response_model=LifeModel)
async def get_life_model():
    row = await _get_life_model_row()
    if not row:
        raise HTTPException(404, "Life model not found — use PUT /api/v1/model to create one")
    return _row_to_life_model(row)


@app.put("/api/v1/model", response_model=LifeModel)
async def upsert_life_model(data: LifeModelUpdate):
    existing = await _get_life_model_row()
    now = datetime.now(timezone.utc)

    if existing is None:
        # Create with defaults
        row = await db.fetchrow(
            """
            INSERT INTO ln_life_model (
                id, user_id, birth_year, target_retirement_age,
                current_net_worth, monthly_income, monthly_expenses,
                monthly_savings_rate, investment_return_pct, passive_income_monthly,
                target_fi_monthly_expense, withdrawal_rate, income_growth_pct, notes, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            RETURNING *
            """,
            uuid.uuid4(), _uid(),
            data.birth_year or 1990,
            data.target_retirement_age or 55,
            data.current_net_worth or 0.0,
            data.monthly_income or 0.0,
            data.monthly_expenses or 0.0,
            data.monthly_savings_rate,
            data.investment_return_pct or 0.07,
            data.passive_income_monthly or 0.0,
            data.target_fi_monthly_expense or 3000.0,
            data.withdrawal_rate or 0.04,
            data.income_growth_pct or 0.03,
            data.notes,
            now,
        )
    else:
        # Update only provided fields
        def _f(key: str, default: Any) -> Any:
            v = getattr(data, key, None)
            return v if v is not None else default

        row = await db.fetchrow(
            """
            UPDATE ln_life_model SET
                birth_year = $1,
                target_retirement_age = $2,
                current_net_worth = $3,
                monthly_income = $4,
                monthly_expenses = $5,
                monthly_savings_rate = $6,
                investment_return_pct = $7,
                passive_income_monthly = $8,
                target_fi_monthly_expense = $9,
                withdrawal_rate = $10,
                income_growth_pct = $11,
                notes = $12,
                updated_at = $13
            WHERE id = $14
            RETURNING *
            """,
            _f("birth_year", existing["birth_year"]),
            _f("target_retirement_age", existing["target_retirement_age"]),
            _f("current_net_worth", existing["current_net_worth"]),
            _f("monthly_income", existing["monthly_income"]),
            _f("monthly_expenses", existing["monthly_expenses"]),
            data.monthly_savings_rate if data.monthly_savings_rate is not None else existing["monthly_savings_rate"],
            _f("investment_return_pct", existing["investment_return_pct"]),
            _f("passive_income_monthly", existing["passive_income_monthly"]),
            _f("target_fi_monthly_expense", existing["target_fi_monthly_expense"]),
            _f("withdrawal_rate", existing["withdrawal_rate"]),
            _f("income_growth_pct", existing["income_growth_pct"]),
            data.notes if data.notes is not None else existing["notes"],
            now,
            existing["id"],
        )

    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_life_model(row)


# ─────────────────────────────────────────────────────────────────────────────
# Goals
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/goals", response_model=list[Goal])
async def list_goals(
    life_area: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    query = "SELECT * FROM ln_goals WHERE user_id = $1"
    params: list[Any] = [_uid()]
    if life_area:
        params.append(life_area)
        query += f" AND life_area = ${len(params)}"
    if status:
        params.append(status)
        query += f" AND status = ${len(params)}"
    query += " ORDER BY created_at DESC"
    params.extend([limit, offset])
    query += f" LIMIT ${len(params)-1} OFFSET ${len(params)}"
    rows = await db.fetch(query, *params)
    return [_row_to_goal(r) for r in rows]


@app.post("/api/v1/goals", response_model=Goal, status_code=201)
async def create_goal(data: GoalCreate):
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        INSERT INTO ln_goals (
            id, user_id, title, description, life_area,
            target_date, status, progress_pct, milestones, created_at, updated_at
        ) VALUES ($1,$2,$3,$4,$5,$6,'active',$7,$8,$9,$9)
        RETURNING *
        """,
        uuid.uuid4(), _uid(), data.title, data.description, data.life_area,
        data.target_date, data.progress_pct, json.dumps(data.milestones), now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_goal(row)


@app.get("/api/v1/goals/{goal_id}", response_model=Goal)
async def get_goal(goal_id: uuid.UUID):
    row = await db.fetchrow(
        "SELECT * FROM ln_goals WHERE id = $1 AND user_id = $2", goal_id, _uid()
    )
    if not row:
        raise HTTPException(404, "Goal not found")
    return _row_to_goal(row)


@app.patch("/api/v1/goals/{goal_id}", response_model=Goal)
async def update_goal(goal_id: uuid.UUID, data: GoalUpdate):
    existing = await db.fetchrow(
        "SELECT * FROM ln_goals WHERE id = $1 AND user_id = $2", goal_id, _uid()
    )
    if not existing:
        raise HTTPException(404, "Goal not found")

    now = datetime.now(timezone.utc)
    new_status = data.status if data.status is not None else existing["status"]
    old_status = existing["status"]

    row = await db.fetchrow(
        """
        UPDATE ln_goals SET
            title = $2, description = $3, life_area = $4,
            target_date = $5, status = $6, progress_pct = $7,
            milestones = $8, updated_at = $9
        WHERE id = $1
        RETURNING *
        """,
        goal_id,
        data.title if data.title is not None else existing["title"],
        data.description if data.description is not None else existing["description"],
        data.life_area if data.life_area is not None else existing["life_area"],
        data.target_date if data.target_date is not None else existing["target_date"],
        new_status,
        data.progress_pct if data.progress_pct is not None else existing["progress_pct"],
        json.dumps(data.milestones) if data.milestones is not None else existing["milestones"],
        now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")

    # Publish NATS event if goal was just completed
    if old_status != "completed" and new_status == "completed":
        await _publish_nats("life.goal.completed", {
            "goal_id": str(goal_id),
            "title": row["title"],
            "life_area": row["life_area"],
        })

    return _row_to_goal(row)


@app.delete("/api/v1/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: uuid.UUID):
    existing = await db.fetchrow(
        "SELECT id FROM ln_goals WHERE id = $1 AND user_id = $2", goal_id, _uid()
    )
    if not existing:
        raise HTTPException(404, "Goal not found")
    await db.execute("DELETE FROM ln_goals WHERE id = $1", goal_id)


# ─────────────────────────────────────────────────────────────────────────────
# Weekly Reviews
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/weekly-reviews", response_model=list[WeeklyReview])
async def list_weekly_reviews(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    rows = await db.fetch(
        "SELECT * FROM ln_weekly_reviews WHERE user_id = $1 ORDER BY week_start DESC LIMIT $2 OFFSET $3",
        _uid(), limit, offset,
    )
    return [_row_to_review(r) for r in rows]


@app.post("/api/v1/weekly-reviews", response_model=WeeklyReview, status_code=201)
async def create_weekly_review(data: WeeklyReviewCreate):
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        INSERT INTO ln_weekly_reviews (
            id, user_id, week_start, accomplishments, challenges,
            learnings, next_week_focus, energy_level, mood, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (user_id, week_start) DO UPDATE SET
            accomplishments = EXCLUDED.accomplishments,
            challenges = EXCLUDED.challenges,
            learnings = EXCLUDED.learnings,
            next_week_focus = EXCLUDED.next_week_focus,
            energy_level = EXCLUDED.energy_level,
            mood = EXCLUDED.mood
        RETURNING *
        """,
        uuid.uuid4(), _uid(), data.week_start,
        data.accomplishments, data.challenges, data.learnings,
        data.next_week_focus, data.energy_level, data.mood, now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    await _publish_nats("life.review.created", {
        "week_start": str(data.week_start),
        "energy_level": data.energy_level,
        "mood": data.mood,
    })
    return _row_to_review(row)


@app.get("/api/v1/weekly-reviews/{review_id}", response_model=WeeklyReview)
async def get_weekly_review(review_id: uuid.UUID):
    row = await db.fetchrow(
        "SELECT * FROM ln_weekly_reviews WHERE id = $1 AND user_id = $2", review_id, _uid()
    )
    if not row:
        raise HTTPException(404, "Weekly review not found")
    return _row_to_review(row)


# ─────────────────────────────────────────────────────────────────────────────
# Health Metrics
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/health-metrics", response_model=list[HealthMetric])
async def list_health_metrics(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    rows = await db.fetch(
        "SELECT * FROM ln_health_metrics WHERE user_id = $1 ORDER BY measured_at DESC LIMIT $2 OFFSET $3",
        _uid(), limit, offset,
    )
    return [_row_to_health_metric(r) for r in rows]


@app.get("/api/v1/health-metrics/latest", response_model=Optional[HealthMetric])
async def get_latest_health_metric():
    row = await db.fetchrow(
        "SELECT * FROM ln_health_metrics WHERE user_id = $1 ORDER BY measured_at DESC LIMIT 1",
        _uid(),
    )
    if not row:
        return None
    return _row_to_health_metric(row)


@app.post("/api/v1/health-metrics", response_model=HealthMetric, status_code=201)
async def log_health_metric(data: HealthMetricCreate):
    now = datetime.now(timezone.utc)
    measured_at = data.measured_at or now
    row = await db.fetchrow(
        """
        INSERT INTO ln_health_metrics (
            id, user_id, measured_at, weight_kg, resting_hr,
            vo2max_estimated, sleep_hours_avg, training_hours_week, source, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING *
        """,
        uuid.uuid4(), _uid(), measured_at,
        data.weight_kg, data.resting_hr, data.vo2max_estimated,
        data.sleep_hours_avg, data.training_hours_week, data.source, now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_health_metric(row)


# ─────────────────────────────────────────────────────────────────────────────
# Career Milestones
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/career", response_model=list[CareerMilestone])
async def list_career_milestones(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    query = "SELECT * FROM ln_career_milestones WHERE user_id = $1"
    params: list[Any] = [_uid()]
    if status:
        params.append(status)
        query += f" AND status = ${len(params)}"
    params.extend([limit, offset])
    query += f" ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}"
    rows = await db.fetch(query, *params)
    return [_row_to_career_milestone(r) for r in rows]


@app.post("/api/v1/career", response_model=CareerMilestone, status_code=201)
async def create_career_milestone(data: CareerMilestoneCreate):
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        INSERT INTO ln_career_milestones (
            id, user_id, title, description, target_date,
            status, achieved_at, impact_score, created_at, updated_at
        ) VALUES ($1,$2,$3,$4,$5,'planned',NULL,$6,$7,$7)
        RETURNING *
        """,
        uuid.uuid4(), _uid(), data.title, data.description,
        data.target_date, data.impact_score, now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_career_milestone(row)


@app.get("/api/v1/career/{milestone_id}", response_model=CareerMilestone)
async def get_career_milestone(milestone_id: uuid.UUID):
    row = await db.fetchrow(
        "SELECT * FROM ln_career_milestones WHERE id = $1 AND user_id = $2",
        milestone_id, _uid(),
    )
    if not row:
        raise HTTPException(404, "Career milestone not found")
    return _row_to_career_milestone(row)


@app.patch("/api/v1/career/{milestone_id}", response_model=CareerMilestone)
async def update_career_milestone(milestone_id: uuid.UUID, data: CareerMilestoneUpdate):
    existing = await db.fetchrow(
        "SELECT * FROM ln_career_milestones WHERE id = $1 AND user_id = $2",
        milestone_id, _uid(),
    )
    if not existing:
        raise HTTPException(404, "Career milestone not found")
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        UPDATE ln_career_milestones SET
            title = $2, description = $3, target_date = $4,
            status = $5, achieved_at = $6, impact_score = $7, updated_at = $8
        WHERE id = $1
        RETURNING *
        """,
        milestone_id,
        data.title if data.title is not None else existing["title"],
        data.description if data.description is not None else existing["description"],
        data.target_date if data.target_date is not None else existing["target_date"],
        data.status if data.status is not None else existing["status"],
        data.achieved_at if data.achieved_at is not None else existing["achieved_at"],
        data.impact_score if data.impact_score is not None else existing["impact_score"],
        now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_career_milestone(row)


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo Simulation
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/simulation/run", response_model=SimulationResult, status_code=201)
async def run_simulation(params: SimulationParams):
    model_row = await _get_life_model_row()
    if not model_row:
        raise HTTPException(
            422,
            "Life model not configured — PUT /api/v1/model first",
        )

    birth_year = model_row["birth_year"]
    current_year = datetime.now(timezone.utc).year
    current_age = current_year - birth_year

    trajectory, fi_p10, fi_p50, fi_p90, fi_target = mc.run_simulation(
        params=params,
        birth_year=birth_year,
        current_age=current_age,
        base_net_worth=float(model_row["current_net_worth"]),
        base_monthly_income=float(model_row["monthly_income"]),
        base_monthly_expenses=float(model_row["monthly_expenses"]),
        base_investment_return=float(model_row["investment_return_pct"]),
        base_inflation=settings.mc_inflation_mean,
        base_income_growth=float(model_row["income_growth_pct"]),
        base_withdrawal_rate=float(model_row["withdrawal_rate"]),
        base_fi_monthly_expense=float(model_row["target_fi_monthly_expense"]),
    )

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    trajectory_json = json.dumps([yp.model_dump() for yp in trajectory])
    params_json = json.dumps(params.model_dump())

    row = await db.fetchrow(
        """
        INSERT INTO ln_simulations (
            id, user_id, scenario_name, parameters, trajectory,
            fi_age_p10, fi_age_p50, fi_age_p90,
            fi_net_worth_target, current_net_worth, run_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        RETURNING *
        """,
        run_id, _uid(), params.scenario_name, params_json,
        trajectory_json, fi_p10, fi_p50, fi_p90,
        fi_target, float(model_row["current_net_worth"]), now,
    )

    # Build result even if DB is unavailable (simulation still ran)
    result = SimulationResult(
        id=run_id if row is None else row["id"],
        user_id=_uid(),
        scenario_name=params.scenario_name,
        parameters=params.model_dump(),
        trajectory=trajectory,
        fi_age_p10=fi_p10,
        fi_age_p50=fi_p50,
        fi_age_p90=fi_p90,
        fi_net_worth_target=fi_target,
        current_net_worth=float(model_row["current_net_worth"]),
        run_at=now,
    )

    await _publish_nats("life.simulation.run", {
        "simulation_id": str(result.id),
        "scenario_name": params.scenario_name,
        "fi_age_p50": fi_p50,
        "fi_target": fi_target,
    })

    return result


@app.get("/api/v1/simulation/runs", response_model=list[SimulationResult])
async def list_simulation_runs(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    rows = await db.fetch(
        "SELECT * FROM ln_simulations WHERE user_id = $1 ORDER BY run_at DESC LIMIT $2 OFFSET $3",
        _uid(), limit, offset,
    )
    return [_row_to_simulation(r) for r in rows]


@app.get("/api/v1/simulation/runs/{run_id}", response_model=SimulationResult)
async def get_simulation_run(run_id: uuid.UUID):
    row = await db.fetchrow(
        "SELECT * FROM ln_simulations WHERE id = $1 AND user_id = $2", run_id, _uid()
    )
    if not row:
        raise HTTPException(404, "Simulation run not found")
    return _row_to_simulation(row)


@app.get("/api/v1/simulation/fi-projection")
async def fi_projection():
    """Quick FI projection using the life model defaults (no DB write)."""
    model_row = await _get_life_model_row()
    if not model_row:
        raise HTTPException(422, "Life model not configured — PUT /api/v1/model first")

    birth_year = model_row["birth_year"]
    current_year = datetime.now(timezone.utc).year
    current_age = current_year - birth_year
    withdrawal_rate = float(model_row["withdrawal_rate"])
    fi_monthly = float(model_row["target_fi_monthly_expense"])
    fi_target = (fi_monthly * 12) / max(withdrawal_rate, 0.001)
    current_nw = float(model_row["current_net_worth"])
    progress_pct = min(100.0, (current_nw / fi_target * 100)) if fi_target > 0 else 0.0

    params = SimulationParams(scenario_name="fi_quick", project_years=40, n_simulations=500)
    trajectory, fi_p10, fi_p50, fi_p90, _ = mc.run_simulation(
        params=params,
        birth_year=birth_year,
        current_age=current_age,
        base_net_worth=current_nw,
        base_monthly_income=float(model_row["monthly_income"]),
        base_monthly_expenses=float(model_row["monthly_expenses"]),
        base_investment_return=float(model_row["investment_return_pct"]),
        base_inflation=settings.mc_inflation_mean,
        base_income_growth=float(model_row["income_growth_pct"]),
        base_withdrawal_rate=withdrawal_rate,
        base_fi_monthly_expense=fi_monthly,
    )

    return {
        "current_age": current_age,
        "current_net_worth": current_nw,
        "fi_target_net_worth": fi_target,
        "fi_progress_pct": progress_pct,
        "fi_age_p10": fi_p10,
        "fi_age_p50": fi_p50,
        "fi_age_p90": fi_p90,
        "years_to_fi_p50": (fi_p50 - current_age) if fi_p50 is not None else None,
        "monthly_savings_needed_for_fi_in_10y": _monthly_savings_for_fi(
            fi_target, current_nw,
            float(model_row["investment_return_pct"]),
            years=10,
        ),
    }


def _monthly_savings_for_fi(fi_target: float, current_nw: float, annual_return: float, years: int) -> Optional[float]:
    """Calculate monthly savings needed to reach fi_target in `years` years."""
    if years <= 0:
        return None
    # FV = PV*(1+r)^n + PMT*((1+r)^n - 1)/r
    # Solve for PMT
    r_annual = annual_return
    n = years
    fv_current = current_nw * ((1 + r_annual) ** n)
    remaining = fi_target - fv_current
    if remaining <= 0:
        return 0.0
    # Annual PMT: remaining = PMT * ((1+r)^n - 1) / r
    if r_annual == 0:
        return remaining / (n * 12)
    annuity_factor = ((1 + r_annual) ** n - 1) / r_annual
    annual_pmt = remaining / annuity_factor
    return annual_pmt / 12


# ─────────────────────────────────────────────────────────────────────────────
# Opportunities
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/opportunities", response_model=list[Opportunity])
async def list_opportunities(
    category: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    query = "SELECT * FROM ln_opportunities WHERE user_id = $1"
    params: list[Any] = [_uid()]
    if category:
        params.append(category)
        query += f" AND category = ${len(params)}"
    params.extend([limit, offset])
    query += f" ORDER BY relevance_score DESC, created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}"
    rows = await db.fetch(query, *params)
    return [_row_to_opportunity(r) for r in rows]


@app.post("/api/v1/opportunities", response_model=Opportunity, status_code=201)
async def create_opportunity(data: OpportunityCreate):
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        INSERT INTO ln_opportunities (
            id, user_id, title, description, category,
            url, relevance_score, source, expires_at, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,'manual',$8,$9)
        RETURNING *
        """,
        uuid.uuid4(), _uid(), data.title, data.description, data.category,
        data.url, data.relevance_score, data.expires_at, now,
    )
    if not row:
        raise HTTPException(503, "Database unavailable")
    return _row_to_opportunity(row)


@app.delete("/api/v1/opportunities/{opportunity_id}", status_code=204)
async def delete_opportunity(opportunity_id: uuid.UUID):
    existing = await db.fetchrow(
        "SELECT id FROM ln_opportunities WHERE id = $1 AND user_id = $2",
        opportunity_id, _uid(),
    )
    if not existing:
        raise HTTPException(404, "Opportunity not found")
    await db.execute("DELETE FROM ln_opportunities WHERE id = $1", opportunity_id)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/dashboard", response_model=LifeNavDashboard)
async def dashboard():
    # Financial snapshot from life model
    model_row = await _get_life_model_row()
    current_nw: Optional[float] = None
    fi_target: Optional[float] = None
    fi_progress: Optional[float] = None
    fi_age_p50: Optional[float] = None
    years_to_fi: Optional[float] = None
    monthly_savings: Optional[float] = None

    if model_row:
        current_nw = float(model_row["current_net_worth"])
        withdrawal_rate = float(model_row["withdrawal_rate"])
        fi_monthly = float(model_row["target_fi_monthly_expense"])
        fi_target = (fi_monthly * 12) / max(withdrawal_rate, 0.001)
        fi_progress = min(100.0, current_nw / fi_target * 100) if fi_target > 0 else 0.0
        inc = float(model_row["monthly_income"])
        exp = float(model_row["monthly_expenses"])
        monthly_savings = inc - exp

    # Latest simulation for FI age
    latest_sim = await db.fetchrow(
        "SELECT fi_age_p50 FROM ln_simulations WHERE user_id = $1 ORDER BY run_at DESC LIMIT 1",
        _uid(),
    )
    if latest_sim and latest_sim["fi_age_p50"] is not None:
        fi_age_p50 = float(latest_sim["fi_age_p50"])
        if model_row:
            birth_year = model_row["birth_year"]
            current_age = datetime.now(timezone.utc).year - birth_year
            years_to_fi = fi_age_p50 - current_age

    # Goals summary
    goal_counts = await db.fetch(
        "SELECT status, life_area, COUNT(*) as cnt FROM ln_goals WHERE user_id = $1 GROUP BY status, life_area",
        _uid(),
    )
    active_goals = sum(r["cnt"] for r in goal_counts if r["status"] == "active")
    completed_goals = sum(r["cnt"] for r in goal_counts if r["status"] == "completed")
    goals_by_area: dict[str, int] = {}
    for r in goal_counts:
        if r["status"] == "active":
            goals_by_area[r["life_area"]] = goals_by_area.get(r["life_area"], 0) + r["cnt"]

    # Health snapshot
    latest_health = await db.fetchrow(
        "SELECT * FROM ln_health_metrics WHERE user_id = $1 ORDER BY measured_at DESC LIMIT 1",
        _uid(),
    )
    latest_vo2max: Optional[float] = None
    latest_weight: Optional[float] = None
    training_hours: Optional[float] = None
    if latest_health:
        latest_vo2max = float(latest_health["vo2max_estimated"]) if latest_health["vo2max_estimated"] else None
        latest_weight = float(latest_health["weight_kg"]) if latest_health["weight_kg"] else None
        training_hours = float(latest_health["training_hours_week"]) if latest_health["training_hours_week"] else None

    # Last weekly review
    latest_review = await db.fetchrow(
        "SELECT week_start FROM ln_weekly_reviews WHERE user_id = $1 ORDER BY week_start DESC LIMIT 1",
        _uid(),
    )
    last_review_date: Optional[date] = None
    days_since_review: Optional[int] = None
    if latest_review:
        last_review_date = latest_review["week_start"]
        days_since_review = (date.today() - last_review_date).days

    # Career counts
    career_counts = await db.fetch(
        "SELECT status, COUNT(*) as cnt FROM ln_career_milestones WHERE user_id = $1 GROUP BY status",
        _uid(),
    )
    planned_ms = sum(r["cnt"] for r in career_counts if r["status"] == "planned")
    achieved_ms = sum(r["cnt"] for r in career_counts if r["status"] == "achieved")

    # Opportunities this week (last 7 days or not yet expired)
    opp_rows = await db.fetch(
        """
        SELECT * FROM ln_opportunities
        WHERE user_id = $1
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY relevance_score DESC, created_at DESC
        LIMIT 5
        """,
        _uid(),
    )
    opportunities = [_row_to_opportunity(r) for r in opp_rows]

    return LifeNavDashboard(
        current_net_worth=current_nw,
        fi_target_net_worth=fi_target,
        fi_progress_pct=fi_progress,
        fi_age_p50=fi_age_p50,
        years_to_fi_p50=years_to_fi,
        monthly_savings=monthly_savings,
        active_goals=active_goals,
        completed_goals=completed_goals,
        goals_by_area=goals_by_area,
        latest_vo2max=latest_vo2max,
        latest_weight_kg=latest_weight,
        training_hours_this_week=training_hours,
        last_weekly_review=last_review_date,
        days_since_last_review=days_since_review,
        planned_milestones=planned_ms,
        achieved_milestones=achieved_ms,
        opportunities_this_week=opportunities,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Oracle registration
# ─────────────────────────────────────────────────────────────────────────────

async def _register_with_oracle() -> None:
    manifest = {
        "service_name": "life-nav",
        "port": settings.port,
        "description": (
            "Life Navigation System — personal life model, goal tracking, "
            "Monte Carlo financial simulation, health metrics, career milestones, "
            "and opportunities radar."
        ),
        "endpoints": [
            {"method": "GET",    "path": "/health",                              "purpose": "Health check"},
            {"method": "GET",    "path": "/api/v1/model",                        "purpose": "Get life model"},
            {"method": "PUT",    "path": "/api/v1/model",                        "purpose": "Upsert life model"},
            {"method": "GET",    "path": "/api/v1/goals",                        "purpose": "List goals"},
            {"method": "POST",   "path": "/api/v1/goals",                        "purpose": "Create goal"},
            {"method": "GET",    "path": "/api/v1/goals/{id}",                   "purpose": "Get goal"},
            {"method": "PATCH",  "path": "/api/v1/goals/{id}",                   "purpose": "Update goal"},
            {"method": "DELETE", "path": "/api/v1/goals/{id}",                   "purpose": "Delete goal"},
            {"method": "GET",    "path": "/api/v1/weekly-reviews",               "purpose": "List weekly reviews"},
            {"method": "POST",   "path": "/api/v1/weekly-reviews",               "purpose": "Create/update weekly review"},
            {"method": "GET",    "path": "/api/v1/weekly-reviews/{id}",          "purpose": "Get weekly review"},
            {"method": "GET",    "path": "/api/v1/health-metrics",               "purpose": "List health metrics"},
            {"method": "GET",    "path": "/api/v1/health-metrics/latest",        "purpose": "Latest health metric"},
            {"method": "POST",   "path": "/api/v1/health-metrics",               "purpose": "Log health metric"},
            {"method": "GET",    "path": "/api/v1/career",                       "purpose": "List career milestones"},
            {"method": "POST",   "path": "/api/v1/career",                       "purpose": "Create career milestone"},
            {"method": "GET",    "path": "/api/v1/career/{id}",                  "purpose": "Get career milestone"},
            {"method": "PATCH",  "path": "/api/v1/career/{id}",                  "purpose": "Update career milestone"},
            {"method": "POST",   "path": "/api/v1/simulation/run",               "purpose": "Run Monte Carlo simulation"},
            {"method": "GET",    "path": "/api/v1/simulation/runs",              "purpose": "List simulation runs"},
            {"method": "GET",    "path": "/api/v1/simulation/runs/{id}",         "purpose": "Get simulation run"},
            {"method": "GET",    "path": "/api/v1/simulation/fi-projection",     "purpose": "Quick FI age projection"},
            {"method": "GET",    "path": "/api/v1/opportunities",                "purpose": "List opportunities"},
            {"method": "POST",   "path": "/api/v1/opportunities",                "purpose": "Add opportunity"},
            {"method": "DELETE", "path": "/api/v1/opportunities/{id}",           "purpose": "Delete opportunity"},
            {"method": "GET",    "path": "/api/v1/dashboard",                    "purpose": "Aggregated dashboard card"},
        ],
        "nats_subjects": [
            {"subject": "life.goal.completed",  "direction": "publish", "purpose": "Goal marked completed"},
            {"subject": "life.simulation.run",  "direction": "publish", "purpose": "Monte Carlo simulation completed"},
            {"subject": "life.review.created",  "direction": "publish", "purpose": "Weekly review submitted"},
        ],
        "source_paths": [{"repo": "claude", "paths": ["services/life-nav/"]}],
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{settings.oracle_url}/oracle/register", json=manifest)
        logger.info("life_nav oracle_registered")
    except Exception as exc:
        logger.warning("life_nav oracle_registration_failed error=%s", exc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("life_nav.main:app", host="0.0.0.0", port=settings.port, reload=False)
