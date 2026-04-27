"""Monte Carlo simulation engine for life/financial scenario modelling.

Runs N simulations of year-by-year net worth trajectory.
Each simulation samples:
  - annual investment return from N(return_mean, return_std)
  - annual inflation from N(inflation_mean, inflation_std)

Computes p10/p50/p90 trajectories and FI crossing age.
"""
from __future__ import annotations

import math
from typing import Optional

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

from .config import settings
from .models import SimulationParams, YearlyProjection


def _fi_crossing_age(
    net_worth_paths: "np.ndarray",  # shape: (n_sims, project_years+1)
    fi_target: float,
    start_age: int,
) -> Optional[float]:
    """Return age at which the median path first reaches fi_target, or None."""
    if not _NUMPY_AVAILABLE:
        return None
    for year_idx in range(net_worth_paths.shape[1]):
        above = np.sum(net_worth_paths[:, year_idx] >= fi_target)
        if above / net_worth_paths.shape[0] >= 0.5:
            return float(start_age + year_idx)
    return None


def _fi_crossing_age_percentile(
    net_worth_paths: "np.ndarray",
    fi_target: float,
    start_age: int,
    percentile: float,  # 0-1, e.g. 0.1 for p10
) -> Optional[float]:
    """Return age at which `percentile` fraction of paths have crossed fi_target."""
    if not _NUMPY_AVAILABLE:
        return None
    for year_idx in range(net_worth_paths.shape[1]):
        above = np.sum(net_worth_paths[:, year_idx] >= fi_target)
        if above / net_worth_paths.shape[0] >= percentile:
            return float(start_age + year_idx)
    return None


def run_simulation(
    params: SimulationParams,
    birth_year: int,
    current_age: int,
    base_net_worth: float,
    base_monthly_income: float,
    base_monthly_expenses: float,
    base_investment_return: float,
    base_inflation: float,
    base_income_growth: float,
    base_withdrawal_rate: float,
    base_fi_monthly_expense: float,
) -> tuple[list[YearlyProjection], Optional[float], Optional[float], Optional[float], float]:
    """Run Monte Carlo simulation. Returns (trajectory, fi_age_p10, fi_age_p50, fi_age_p90, fi_target)."""

    # Resolve params — override base values with scenario overrides
    net_worth = params.current_net_worth if params.current_net_worth is not None else base_net_worth
    monthly_income = params.monthly_income if params.monthly_income is not None else base_monthly_income
    monthly_expenses = params.monthly_expenses if params.monthly_expenses is not None else base_monthly_expenses
    return_mean = params.investment_return_mean if params.investment_return_mean is not None else base_investment_return
    return_std = params.investment_return_std if params.investment_return_std is not None else settings.mc_return_std
    inflation_mean = params.inflation_mean if params.inflation_mean is not None else base_inflation
    inflation_std = params.inflation_std if params.inflation_std is not None else settings.mc_inflation_std
    income_growth = params.income_growth_pct if params.income_growth_pct is not None else base_income_growth
    withdrawal_rate = params.withdrawal_rate if params.withdrawal_rate is not None else base_withdrawal_rate
    fi_expense = params.target_fi_monthly_expense if params.target_fi_monthly_expense is not None else base_fi_monthly_expense
    n_sims = params.n_simulations if params.n_simulations is not None else settings.mc_simulations
    project_years = params.project_years

    # FI target: net worth needed so SWR covers fi_expense per month
    fi_target = (fi_expense * 12) / max(withdrawal_rate, 0.001)

    if not _NUMPY_AVAILABLE:
        # Deterministic fallback without numpy — single path
        trajectory = _deterministic_trajectory(
            net_worth, monthly_income, monthly_expenses,
            return_mean, inflation_mean, income_growth,
            current_age, project_years,
        )
        fi_age = None
        for yp in trajectory:
            if yp.p50 >= fi_target:
                fi_age = float(yp.age)
                break
        return trajectory, fi_age, fi_age, fi_age, fi_target

    import numpy as np

    rng = np.random.default_rng()

    # Sample annual returns and inflation: shape (n_sims, project_years)
    annual_returns = rng.normal(return_mean, return_std, size=(n_sims, project_years))
    annual_inflations = rng.normal(inflation_mean, inflation_std, size=(n_sims, project_years))
    # Clamp returns to avoid extreme negatives
    annual_returns = np.clip(annual_returns, -0.5, 0.5)
    annual_inflations = np.clip(annual_inflations, 0.0, 0.15)

    # net worth paths: shape (n_sims, project_years + 1)
    nw = np.zeros((n_sims, project_years + 1))
    nw[:, 0] = net_worth

    current_income = monthly_income
    current_expenses = monthly_expenses

    for y in range(project_years):
        # Grow income and expenses
        year_income = current_income * ((1 + income_growth) ** y)
        year_expenses = current_expenses * ((1 + annual_inflations[:, y]))
        annual_savings = (year_income - year_expenses) * 12
        # Net worth grows by savings + return
        nw[:, y + 1] = (nw[:, y] + annual_savings) * (1 + annual_returns[:, y])

    # Build p10/p50/p90 trajectory
    trajectory: list[YearlyProjection] = []
    for y in range(project_years + 1):
        p10 = float(np.percentile(nw[:, y], 10))
        p50 = float(np.percentile(nw[:, y], 50))
        p90 = float(np.percentile(nw[:, y], 90))
        trajectory.append(YearlyProjection(
            year=birth_year + current_age + y,
            age=current_age + y,
            p10=p10,
            p50=p50,
            p90=p90,
        ))

    fi_age_p10 = _fi_crossing_age_percentile(nw, fi_target, current_age, 0.1)
    fi_age_p50 = _fi_crossing_age_percentile(nw, fi_target, current_age, 0.5)
    fi_age_p90 = _fi_crossing_age_percentile(nw, fi_target, current_age, 0.9)

    return trajectory, fi_age_p10, fi_age_p50, fi_age_p90, fi_target


def _deterministic_trajectory(
    net_worth: float,
    monthly_income: float,
    monthly_expenses: float,
    return_rate: float,
    inflation_rate: float,
    income_growth: float,
    current_age: int,
    project_years: int,
) -> list[YearlyProjection]:
    """Single-path deterministic fallback when numpy is unavailable."""
    trajectory = []
    nw = net_worth
    for y in range(project_years + 1):
        year_income = monthly_income * ((1 + income_growth) ** y)
        year_expenses = monthly_expenses * ((1 + inflation_rate) ** y)
        trajectory.append(YearlyProjection(
            year=2026 + y,
            age=current_age + y,
            p10=nw * 0.7,
            p50=nw,
            p90=nw * 1.3,
        ))
        annual_savings = (year_income - year_expenses) * 12
        nw = (nw + annual_savings) * (1 + return_rate)
    return trajectory
