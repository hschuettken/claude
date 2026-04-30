"""Tests for the Life Navigation System.

All tests run without a real database, NATS, or external APIs.
db.py returns None/[] when pool is absent; modules handle that gracefully.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts():
    return datetime.now(timezone.utc)


def _make_model_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "birth_year": 1990,
        "target_retirement_age": 55,
        "current_net_worth": 150000.0,
        "monthly_income": 6000.0,
        "monthly_expenses": 3500.0,
        "monthly_savings_rate": None,
        "investment_return_pct": 0.07,
        "passive_income_monthly": 0.0,
        "target_fi_monthly_expense": 3000.0,
        "withdrawal_rate": 0.04,
        "income_growth_pct": 0.03,
        "notes": None,
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_goal_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "title": "Run a half marathon",
        "description": "Train and complete a half marathon",
        "life_area": "health",
        "target_date": date(2026, 12, 31),
        "status": "active",
        "progress_pct": 20.0,
        "milestones": "[]",
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_review_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "week_start": date(2026, 4, 21),
        "accomplishments": "Finished project X",
        "challenges": "Lack of sleep",
        "learnings": "Delegate more",
        "next_week_focus": "Rest and recovery",
        "energy_level": 7,
        "mood": 8,
        "created_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_health_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "measured_at": _ts(),
        "weight_kg": 78.5,
        "resting_hr": 55,
        "vo2max_estimated": 48.0,
        "sleep_hours_avg": 7.5,
        "training_hours_week": 5.0,
        "source": "manual",
        "created_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_career_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "title": "Lead a product launch",
        "description": "End-to-end product ownership",
        "target_date": date(2027, 6, 1),
        "achieved_at": None,
        "status": "planned",
        "impact_score": 8,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_opportunity_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "title": "Senior Engineer at Startup X",
        "description": "Remote-friendly, AI/ML focus",
        "category": "job",
        "url": "https://example.com/job/123",
        "relevance_score": 0.85,
        "source": "manual",
        "expires_at": None,
        "created_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


def _make_simulation_row(**kwargs) -> dict:
    trajectory = json.dumps([
        {"year": 2026, "age": 36, "p10": 120000, "p50": 150000, "p90": 180000},
        {"year": 2027, "age": 37, "p10": 145000, "p50": 185000, "p90": 230000},
    ])
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "scenario_name": "baseline",
        "parameters": json.dumps({"scenario_name": "baseline", "project_years": 40}),
        "trajectory": trajectory,
        "fi_age_p10": 58.0,
        "fi_age_p50": 52.0,
        "fi_age_p90": 47.0,
        "fi_net_worth_target": 900000.0,
        "current_net_worth": 150000.0,
        "run_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Config tests
# ─────────────────────────────────────────────────────────────────────────────

def test_config_defaults():
    from life_nav.config import Settings
    s = Settings()
    assert s.port == 8243
    assert s.mc_simulations == 1000
    assert s.mc_return_mean == 0.07
    assert s.mc_return_std == 0.15
    assert s.default_user == "henning"


# ─────────────────────────────────────────────────────────────────────────────
# Model tests
# ─────────────────────────────────────────────────────────────────────────────

def test_life_model_update():
    from life_nav.models import LifeModelUpdate
    m = LifeModelUpdate(current_net_worth=200000, monthly_income=7000)
    assert m.current_net_worth == 200000
    assert m.monthly_income == 7000
    assert m.monthly_expenses is None


def test_goal_create_defaults():
    from life_nav.models import GoalCreate
    g = GoalCreate(title="Learn Python")
    assert g.life_area == "other"
    assert g.progress_pct == 0.0
    assert g.milestones == []


def test_goal_progress_validation():
    from life_nav.models import GoalCreate
    import pydantic
    with pytest.raises((ValueError, pydantic.ValidationError)):
        GoalCreate(title="Bad", progress_pct=150.0)


def test_weekly_review_create():
    from life_nav.models import WeeklyReviewCreate
    r = WeeklyReviewCreate(week_start=date(2026, 4, 21))
    assert r.energy_level == 5
    assert r.mood == 5
    assert r.accomplishments == ""


def test_health_metric_create():
    from life_nav.models import HealthMetricCreate
    h = HealthMetricCreate(weight_kg=78.5, vo2max_estimated=47.0)
    assert h.source == "manual"
    assert h.sleep_hours_avg is None


def test_career_milestone_create():
    from life_nav.models import CareerMilestoneCreate
    m = CareerMilestoneCreate(title="CTO role", impact_score=10)
    assert m.impact_score == 10
    assert m.target_date is None


def test_simulation_params_defaults():
    from life_nav.models import SimulationParams
    p = SimulationParams()
    assert p.project_years == 40
    assert p.scenario_name == "baseline"
    assert p.withdrawal_rate is None


def test_opportunity_create():
    from life_nav.models import OpportunityCreate
    o = OpportunityCreate(title="AI conference", category="learning")
    assert o.relevance_score == 0.5
    assert o.category == "learning"


def test_life_nav_dashboard_defaults():
    from life_nav.models import LifeNavDashboard
    d = LifeNavDashboard()
    assert d.active_goals == 0
    assert d.opportunities_this_week == []
    assert d.goals_by_area == {}


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo tests
# ─────────────────────────────────────────────────────────────────────────────

def test_monte_carlo_basic():
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc
    params = SimulationParams(
        scenario_name="test",
        project_years=10,
        n_simulations=100,
    )
    trajectory, fi_p10, fi_p50, fi_p90, fi_target = mc.run_simulation(
        params=params,
        birth_year=1990,
        current_age=36,
        base_net_worth=150000,
        base_monthly_income=6000,
        base_monthly_expenses=3500,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0.03,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=3000,
    )
    assert len(trajectory) == 11  # project_years + 1
    assert trajectory[0].age == 36
    assert trajectory[-1].age == 46
    assert trajectory[0].p10 <= trajectory[0].p50 <= trajectory[0].p90
    # FI target for 3000/month at 4% SWR = 900_000
    assert abs(fi_target - 900_000) < 1


def test_monte_carlo_fi_crossing():
    """With very high savings rate and long horizon, FI should be found."""
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc
    params = SimulationParams(
        scenario_name="aggressive",
        project_years=30,
        n_simulations=200,
        investment_return_mean=0.08,
        investment_return_std=0.10,
    )
    _, fi_p10, fi_p50, fi_p90, _ = mc.run_simulation(
        params=params,
        birth_year=1990,
        current_age=36,
        base_net_worth=500000,    # already have 500k
        base_monthly_income=10000,
        base_monthly_expenses=4000,
        base_investment_return=0.08,
        base_inflation=0.03,
        base_income_growth=0.03,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=3000,
    )
    # With 6000/month savings and 500k start, FI at 3000/month (target 900k) should be found quickly
    assert fi_p50 is not None
    assert fi_p50 < 60  # should reach FI before 60


def test_monte_carlo_trajectory_grows():
    """Positive savings + positive return → median trajectory grows over time."""
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc
    params = SimulationParams(project_years=20, n_simulations=300)
    trajectory, _, _, _, _ = mc.run_simulation(
        params=params,
        birth_year=1990,
        current_age=36,
        base_net_worth=100000,
        base_monthly_income=5000,
        base_monthly_expenses=3000,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0.02,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=3000,
    )
    # Median should grow significantly over 20 years
    assert trajectory[-1].p50 > trajectory[0].p50 * 2


def test_monte_carlo_p10_below_p90():
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc
    params = SimulationParams(project_years=15, n_simulations=200)
    trajectory, _, _, _, _ = mc.run_simulation(
        params=params,
        birth_year=1990,
        current_age=36,
        base_net_worth=50000,
        base_monthly_income=4000,
        base_monthly_expenses=3000,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0.02,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=2500,
    )
    # At year 10+, spread should exist
    for yp in trajectory[5:]:
        assert yp.p10 <= yp.p90


def test_fi_target_calculation():
    """FI target = (monthly_expense * 12) / withdrawal_rate."""
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc
    params = SimulationParams(project_years=5, n_simulations=100, withdrawal_rate=0.04)
    _, _, _, _, fi_target = mc.run_simulation(
        params=params,
        birth_year=1990,
        current_age=36,
        base_net_worth=0,
        base_monthly_income=0,
        base_monthly_expenses=0,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=2500,
    )
    # 2500 * 12 / 0.04 = 750_000
    assert abs(fi_target - 750_000) < 1


def test_monte_carlo_scenario_override():
    """Scenario with higher income should reach FI faster (p50 lower age)."""
    from life_nav.models import SimulationParams
    from life_nav import monte_carlo as mc

    base_params = SimulationParams(project_years=30, n_simulations=300)
    _, _, fi_base, _, _ = mc.run_simulation(
        params=base_params,
        birth_year=1990,
        current_age=36,
        base_net_worth=100000,
        base_monthly_income=5000,
        base_monthly_expenses=3500,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0.03,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=3000,
    )

    high_income_params = SimulationParams(
        project_years=30, n_simulations=300,
        monthly_income=12000,  # double income
    )
    _, _, fi_high, _, _ = mc.run_simulation(
        params=high_income_params,
        birth_year=1990,
        current_age=36,
        base_net_worth=100000,
        base_monthly_income=5000,
        base_monthly_expenses=3500,
        base_investment_return=0.07,
        base_inflation=0.03,
        base_income_growth=0.03,
        base_withdrawal_rate=0.04,
        base_fi_monthly_expense=3000,
    )
    # Higher income → FI should be reached earlier (or at least not later)
    if fi_base is not None and fi_high is not None:
        assert fi_high <= fi_base


def test_monthly_savings_for_fi_helper():
    """_monthly_savings_for_fi returns non-negative value when current NW < target."""
    from life_nav.main import _monthly_savings_for_fi
    result = _monthly_savings_for_fi(
        fi_target=900_000,
        current_nw=150_000,
        annual_return=0.07,
        years=10,
    )
    assert result is not None
    assert result > 0


def test_monthly_savings_for_fi_already_fi():
    """Returns 0 when current NW already exceeds FI target."""
    from life_nav.main import _monthly_savings_for_fi
    result = _monthly_savings_for_fi(
        fi_target=500_000,
        current_nw=900_000,
        annual_return=0.07,
        years=10,
    )
    assert result == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# DB no-pool graceful fallback
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_fetch_no_pool():
    from life_nav import db
    # Without init_pool, pool is None → returns empty list
    rows = await db.fetch("SELECT 1")
    assert rows == []


@pytest.mark.asyncio
async def test_db_fetchrow_no_pool():
    from life_nav import db
    row = await db.fetchrow("SELECT 1")
    assert row is None


@pytest.mark.asyncio
async def test_db_fetchval_no_pool():
    from life_nav import db
    val = await db.fetchval("SELECT 1")
    assert val is None


@pytest.mark.asyncio
async def test_db_execute_no_pool():
    from life_nav import db
    # Should not raise
    await db.execute("SELECT 1")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI integration tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def test_client():
    from httpx import AsyncClient, ASGITransport
    from life_nav.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    async with test_client as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_get_model_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/model")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_model_create(test_client):
    row = _make_model_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(side_effect=[None, row])  # first=None (no existing), second=new row
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.put("/api/v1/model", json={
                "birth_year": 1990,
                "monthly_income": 6000,
                "monthly_expenses": 3500,
                "current_net_worth": 150000,
                "target_fi_monthly_expense": 3000,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["birth_year"] == 1990


@pytest.mark.asyncio
async def test_upsert_model_update(test_client):
    """PUT with an existing model should call UPDATE path, not INSERT."""
    existing = _make_model_row()
    updated = _make_model_row(monthly_income=8000.0, current_net_worth=200000.0)
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            # First fetchrow = existing model found, second = updated row returned
            mock_db.fetchrow = AsyncMock(side_effect=[existing, updated])
            resp = await client.put("/api/v1/model", json={
                "monthly_income": 8000,
                "current_net_worth": 200000,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["monthly_income"] == 8000.0
            assert data["current_net_worth"] == 200000.0
            # Verify UPDATE was attempted (fetchrow called twice: get + update)
            assert mock_db.fetchrow.call_count == 2


@pytest.mark.asyncio
async def test_goals_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/goals")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_create_goal(test_client):
    row = _make_goal_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/goals", json={
                "title": "Run a half marathon",
                "life_area": "health",
                "progress_pct": 20.0,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["title"] == "Run a half marathon"
            assert data["life_area"] == "health"


@pytest.mark.asyncio
async def test_get_goal_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get(f"/api/v1/goals/{uuid.uuid4()}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_goal_completion(test_client):
    existing = _make_goal_row(status="active")
    updated = _make_goal_row(status="completed", progress_pct=100.0)
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db, \
             patch("life_nav.main._publish_nats", new=AsyncMock()):
            mock_db.fetchrow = AsyncMock(side_effect=[existing, updated])
            resp = await client.patch(f"/api/v1/goals/{existing['id']}", json={
                "status": "completed",
                "progress_pct": 100.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_delete_goal(test_client):
    existing = _make_goal_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=existing)
            mock_db.execute = AsyncMock()
            resp = await client.delete(f"/api/v1/goals/{existing['id']}")
            assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_goal_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.delete(f"/api/v1/goals/{uuid.uuid4()}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_weekly_reviews_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/weekly-reviews")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_create_weekly_review(test_client):
    row = _make_review_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db, \
             patch("life_nav.main._publish_nats", new=AsyncMock()):
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/weekly-reviews", json={
                "week_start": "2026-04-21",
                "accomplishments": "Finished project X",
                "energy_level": 7,
                "mood": 8,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["energy_level"] == 7


@pytest.mark.asyncio
async def test_health_metrics_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/health-metrics")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_log_health_metric(test_client):
    row = _make_health_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/health-metrics", json={
                "weight_kg": 78.5,
                "resting_hr": 55,
                "vo2max_estimated": 48.0,
                "training_hours_week": 5.0,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["weight_kg"] == 78.5
            assert data["vo2max_estimated"] == 48.0


@pytest.mark.asyncio
async def test_latest_health_metric_none(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get("/api/v1/health-metrics/latest")
            assert resp.status_code == 200
            assert resp.json() is None


@pytest.mark.asyncio
async def test_career_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/career")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_create_career_milestone(test_client):
    row = _make_career_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/career", json={
                "title": "Lead a product launch",
                "impact_score": 8,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["impact_score"] == 8
            assert data["status"] == "planned"


@pytest.mark.asyncio
async def test_simulation_run_no_model(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.post("/api/v1/simulation/run", json={"scenario_name": "test"})
            assert resp.status_code == 422


@pytest.mark.asyncio
async def test_simulation_run_with_model(test_client):
    model_row = _make_model_row()
    sim_row = _make_simulation_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db, \
             patch("life_nav.main._publish_nats", new=AsyncMock()):
            # First fetchrow call = get_life_model, second = insert sim
            mock_db.fetchrow = AsyncMock(side_effect=[model_row, sim_row])
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.post("/api/v1/simulation/run", json={
                "scenario_name": "baseline",
                "project_years": 10,
                "n_simulations": 100,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["scenario_name"] == "baseline"
            assert "trajectory" in data
            assert len(data["trajectory"]) > 0


@pytest.mark.asyncio
async def test_simulation_runs_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/simulation/runs")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_fi_projection_no_model(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get("/api/v1/simulation/fi-projection")
            assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fi_projection_with_model(test_client):
    model_row = _make_model_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=model_row)
            resp = await client.get("/api/v1/simulation/fi-projection")
            assert resp.status_code == 200
            data = resp.json()
            assert "current_net_worth" in data
            assert "fi_target_net_worth" in data
            assert "fi_progress_pct" in data
            assert data["fi_target_net_worth"] == pytest.approx(900_000.0, rel=0.01)


@pytest.mark.asyncio
async def test_opportunities_list_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/opportunities")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_create_opportunity(test_client):
    row = _make_opportunity_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/opportunities", json={
                "title": "Senior Engineer at Startup X",
                "category": "job",
                "relevance_score": 0.85,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["category"] == "job"
            assert data["relevance_score"] == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_delete_opportunity_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.delete(f"/api/v1/opportunities/{uuid.uuid4()}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_no_data(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/dashboard")
            assert resp.status_code == 200
            data = resp.json()
            assert data["active_goals"] == 0
            assert data["current_net_worth"] is None


@pytest.mark.asyncio
async def test_dashboard_with_model(test_client):
    model_row = _make_model_row()
    sim_row = {"fi_age_p50": 52.0}
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            # dashboard fetchrow order: get_life_model, latest_sim, latest_health, latest_review
            mock_db.fetchrow = AsyncMock(side_effect=[model_row, sim_row, None, None])
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/dashboard")
            assert resp.status_code == 200
            data = resp.json()
            assert data["current_net_worth"] == pytest.approx(150000.0)
            assert data["fi_age_p50"] == pytest.approx(52.0)


@pytest.mark.asyncio
async def test_simulation_run_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get(f"/api/v1/simulation/runs/{uuid.uuid4()}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_career_milestone_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get(f"/api/v1/career/{uuid.uuid4()}")
            assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Opportunity radar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_opportunity_refresh_no_results(test_client):
    """Refresh with no external results stores nothing and returns 0 added."""
    async with test_client as client:
        with patch("life_nav.main.radar") as mock_radar, \
             patch("life_nav.main.db") as mock_db:
            mock_radar.fetch_job_opportunities = AsyncMock(return_value=[])
            mock_radar.fetch_etf_opportunities = AsyncMock(return_value=[])
            mock_radar.fetch_travel_opportunities = AsyncMock(return_value=[])
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.post(
                "/api/v1/opportunities/refresh",
                params={"categories": ["job", "investment", "travel"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["added"] == 0
            assert set(data["categories_searched"]) == {"job", "investment", "travel"}


@pytest.mark.asyncio
async def test_opportunity_refresh_stores_jobs(test_client):
    """Refresh with job results stores them and increments added count."""
    job = {
        "title": "Senior Python Engineer",
        "description": "Remote-first role at AI startup",
        "category": "job",
        "url": "https://example.com/jobs/1",
        "relevance_score": 0.8,
        "source": "web_search",
        "expires_at": None,
    }
    async with test_client as client:
        with patch("life_nav.main.radar") as mock_radar, \
             patch("life_nav.main.db") as mock_db:
            mock_radar.fetch_job_opportunities = AsyncMock(return_value=[job])
            mock_radar.fetch_etf_opportunities = AsyncMock(return_value=[])
            mock_radar.fetch_travel_opportunities = AsyncMock(return_value=[])
            # fetchrow returns a row (INSERT succeeded)
            mock_db.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})
            resp = await client.post(
                "/api/v1/opportunities/refresh",
                params={"categories": ["job"], "job_keywords": ["python", "engineer"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["added"] == 1


@pytest.mark.asyncio
async def test_opportunity_refresh_etf_and_travel(test_client):
    """Investment and travel categories are fetched and stored."""
    etf = {
        "title": "Vanguard Total Market ETF (VTI)",
        "description": "$220.10 (+1.2% today)",
        "category": "investment",
        "url": "https://finance.yahoo.com/quote/VTI",
        "relevance_score": 0.7,
        "source": "yahoo_finance",
        "expires_at": None,
    }
    travel = {
        "title": "Flight deal: Berlin → NYC €350",
        "description": "Limited seats available",
        "category": "travel",
        "url": "https://deals.example.com/1",
        "relevance_score": 0.75,
        "source": "rss_feed",
        "expires_at": None,
    }
    async with test_client as client:
        with patch("life_nav.main.radar") as mock_radar, \
             patch("life_nav.main.db") as mock_db:
            mock_radar.fetch_job_opportunities = AsyncMock(return_value=[])
            mock_radar.fetch_etf_opportunities = AsyncMock(return_value=[etf])
            mock_radar.fetch_travel_opportunities = AsyncMock(return_value=[travel])
            mock_db.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})
            resp = await client.post(
                "/api/v1/opportunities/refresh",
                params={"categories": ["investment", "travel"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["added"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Cook Planner
# ─────────────────────────────────────────────────────────────────────────────

def _make_meal_plan_row(**kwargs) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": "henning",
        "plan_date": date(2026, 4, 28),
        "breakfast": "Oatmeal with berries",
        "lunch": "Chicken salad",
        "dinner": "Salmon with veggies",
        "snacks": "Apple, nuts",
        "notes": "High protein day",
        "calories_target": 2200,
        "protein_g_target": 180.0,
        "carbs_g_target": 220.0,
        "fat_g_target": 70.0,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    defaults.update(kwargs)
    return defaults


@pytest.mark.asyncio
async def test_list_meal_plans_empty(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/meal-plans")
            assert resp.status_code == 200
            assert resp.json() == []


@pytest.mark.asyncio
async def test_create_meal_plan(test_client):
    row = _make_meal_plan_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            resp = await client.post("/api/v1/meal-plans", json={
                "plan_date": "2026-04-28",
                "breakfast": "Oatmeal with berries",
                "lunch": "Chicken salad",
                "dinner": "Salmon with veggies",
                "calories_target": 2200,
                "protein_g_target": 180.0,
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["breakfast"] == "Oatmeal with berries"
            assert data["calories_target"] == 2200
            assert data["protein_g_target"] == pytest.approx(180.0)


@pytest.mark.asyncio
async def test_get_meal_plan_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.get(f"/api/v1/meal-plans/{uuid.uuid4()}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_meal_plan(test_client):
    row = _make_meal_plan_row()
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=row)
            mock_db.execute = AsyncMock()
            resp = await client.delete(f"/api/v1/meal-plans/{row['id']}")
            assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_meal_plan_not_found(test_client):
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.delete(f"/api/v1/meal-plans/{uuid.uuid4()}")
            assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — intervals.icu sync
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intervals_sync_not_configured(test_client):
    """Returns 422 when intervals.icu is not configured."""
    async with test_client as client:
        with patch("life_nav.main.settings") as mock_settings:
            mock_settings.intervals_api_key = None
            mock_settings.intervals_athlete_id = None
            resp = await client.post("/api/v1/health-metrics/sync/intervals-icu")
            assert resp.status_code == 422


@pytest.mark.asyncio
async def test_intervals_sync_success(test_client):
    """Syncs activities from intervals.icu and stores health metrics."""
    activities = [
        {
            "start_date_local": "2026-04-27T08:00:00",
            "moving_time": 3600,
            "icu_vo2max": 48.5,
        },
        {
            "start_date_local": "2026-04-25T07:30:00",
            "moving_time": 5400,
            "icu_vo2max": None,
        },
    ]
    async with test_client as client:
        with patch("life_nav.main.settings") as mock_settings, \
             patch("life_nav.main.db") as mock_db, \
             patch("httpx.AsyncClient") as mock_http:
            mock_settings.intervals_api_key = "test-key"
            mock_settings.intervals_athlete_id = "i12345"
            # Mock HTTP response
            mock_resp = MagicMock()
            mock_resp.json.return_value = activities
            mock_resp.raise_for_status = MagicMock()
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=mock_resp)
            ))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
            # DB returns a row for each insert (both succeed)
            mock_db.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})
            resp = await client.post("/api/v1/health-metrics/sync/intervals-icu")
            assert resp.status_code == 200
            data = resp.json()
            assert data["synced"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Multi-objective optimizer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_optimize_no_data(test_client):
    """Optimizer returns a result even with no goals or health data."""
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.post("/api/v1/optimize", json={
                "finance_weight": 0.5,
                "health_weight": 0.3,
                "career_weight": 0.1,
                "relationships_weight": 0.1,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "recommendations" in data
            assert data["dominant_objective"] == "finance"
            assert "trade_off_summary" in data


@pytest.mark.asyncio
async def test_optimize_with_goals(test_client):
    """Optimizer scores active goals and returns them as recommendations."""
    goals = [
        _make_goal_row(title="Get promoted", life_area="career", progress_pct=30.0),
        _make_goal_row(title="Run marathon", life_area="health", progress_pct=50.0),
        _make_goal_row(title="Save €50k", life_area="finance", progress_pct=10.0),
    ]
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(side_effect=[
                goals,     # active goals query
                [],        # career milestones query
            ])
            mock_db.fetchrow = AsyncMock(return_value=None)  # no life model, no health
            resp = await client.post("/api/v1/optimize", json={
                "career_weight": 0.4,
                "finance_weight": 0.3,
                "health_weight": 0.2,
                "relationships_weight": 0.1,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["recommendations"]) > 0
            assert data["dominant_objective"] == "career"
            # All recommendations should have priority_score in [0, 1]
            for rec in data["recommendations"]:
                assert 0.0 <= rec["priority_score"] <= 1.0
                assert 0.0 <= rec["impact_score"] <= 1.0


@pytest.mark.asyncio
async def test_optimize_weights_normalised(test_client):
    """Optimizer normalises weights that don't sum to 1."""
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(return_value=[])
            mock_db.fetchrow = AsyncMock(return_value=None)
            resp = await client.post("/api/v1/optimize", json={
                "career_weight": 1.0,
                "finance_weight": 1.0,
                "health_weight": 1.0,
                "relationships_weight": 1.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            total_w = sum(data["weights_used"].values())
            assert abs(total_w - 1.0) < 0.01


@pytest.mark.asyncio
async def test_optimize_finance_heavy_generates_recommendation(test_client):
    """Finance-heavy optimization generates savings-rate recommendation."""
    model = _make_model_row(
        monthly_income=6000.0,
        monthly_expenses=5000.0,  # high expense ratio
        current_net_worth=50000.0,
        target_fi_monthly_expense=3000.0,
        withdrawal_rate=0.04,
    )
    async with test_client as client:
        with patch("life_nav.main.db") as mock_db:
            mock_db.fetch = AsyncMock(side_effect=[
                [],   # goals
                [],   # career milestones
            ])
            mock_db.fetchrow = AsyncMock(side_effect=[
                model,  # get_life_model_row
                None,   # health metrics
            ])
            resp = await client.post("/api/v1/optimize", json={
                "finance_weight": 0.7,
                "career_weight": 0.1,
                "health_weight": 0.1,
                "relationships_weight": 0.1,
            })
            assert resp.status_code == 200
            data = resp.json()
            areas = [r["life_area"] for r in data["recommendations"]]
            assert "finance" in areas


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — opportunity radar unit tests (no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_radar_fetch_jobs_http_error():
    """fetch_job_opportunities returns [] on HTTP error."""
    from life_nav import opportunity_radar as radar
    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await radar.fetch_job_opportunities(["python"])
        assert result == []


@pytest.mark.asyncio
async def test_radar_fetch_etf_http_error():
    """fetch_etf_opportunities returns [] on HTTP error."""
    from life_nav import opportunity_radar as radar
    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await radar.fetch_etf_opportunities()
        assert result == []


@pytest.mark.asyncio
async def test_radar_fetch_travel_http_error():
    """fetch_travel_opportunities returns [] on HTTP error."""
    from life_nav import opportunity_radar as radar
    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await radar.fetch_travel_opportunities()
        assert result == []


@pytest.mark.asyncio
async def test_radar_fetch_etf_parses_response():
    """fetch_etf_opportunities correctly maps Yahoo Finance quote response."""
    from life_nav import opportunity_radar as radar
    yahoo_response = {
        "quoteResponse": {
            "result": [
                {
                    "symbol": "VTI",
                    "longName": "Vanguard Total Stock Market ETF",
                    "regularMarketPrice": 220.5,
                    "regularMarketChangePercent": 1.2,
                }
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = yahoo_response
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_http:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await radar.fetch_etf_opportunities(symbols=["VTI"])
    assert len(result) == 1
    assert result[0]["category"] == "investment"
    assert "VTI" in result[0]["title"]
    assert result[0]["relevance_score"] > 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — model validation
# ─────────────────────────────────────────────────────────────────────────────

def test_meal_plan_create():
    from life_nav.models import MealPlanCreate
    m = MealPlanCreate(plan_date=date(2026, 4, 28), breakfast="Oats", dinner="Salmon")
    assert m.lunch == ""
    assert m.calories_target is None


def test_optimize_request_defaults():
    from life_nav.models import OptimizeRequest
    req = OptimizeRequest()
    assert req.career_weight == 0.25
    assert req.time_horizon_years == 5


def test_optimize_request_validation():
    from life_nav.models import OptimizeRequest
    import pydantic
    with pytest.raises((ValueError, pydantic.ValidationError)):
        OptimizeRequest(career_weight=1.5)  # > 1.0


def test_action_recommendation():
    from life_nav.models import ActionRecommendation
    rec = ActionRecommendation(
        title="Do X",
        description="Because Y",
        life_area="health",
        priority_score=0.8,
        impact_score=0.7,
    )
    assert rec.effort_score == 0.5
    assert rec.source == "optimizer"


def test_opportunity_refresh_result():
    from life_nav.models import OpportunityRefreshResult
    r = OpportunityRefreshResult(added=3, skipped=1, categories_searched=["job"])
    assert r.added == 3
    assert r.errors == []
