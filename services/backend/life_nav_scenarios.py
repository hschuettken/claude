"""Life Navigation Monte Carlo Scenarios Engine.

Phase 3: Monte Carlo simulation for life goals with fan charts,
sensitivity analysis, and "what moves the needle" insights.

Provides:
- Goal scenario simulation with probabilistic outcomes
- Sensitivity analysis (which variables have most impact)
- Fan chart generation (min/median/max projections)
- Recommendation generation based on simulations
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import uuid
from datetime import datetime, date, timedelta
import random
import statistics

from pydantic import BaseModel, Field

logger = logging.getLogger("life_nav.scenarios")


class GoalCategory(str, Enum):
    """Life goal categories."""
    training = "training"
    project = "project"
    health = "health"
    financial = "financial"
    relationship = "relationship"
    career = "career"
    learning = "learning"
    habits = "habits"


class DistributionType(str, Enum):
    """Distribution types for variable variance."""
    uniform = "uniform"
    normal = "normal"
    triangular = "triangular"


@dataclass
class Variable:
    """A variable in a scenario (e.g., training hours, project time allocation)."""
    name: str
    current_value: float
    min_value: float
    max_value: float
    distribution: DistributionType = DistributionType.normal
    std_dev: Optional[float] = None  # For normal distribution
    description: str = ""
    
    def sample(self) -> float:
        """Generate a random sample from this variable's distribution."""
        if self.distribution == DistributionType.uniform:
            return random.uniform(self.min_value, self.max_value)
        elif self.distribution == DistributionType.normal:
            std = self.std_dev or (self.max_value - self.min_value) / 4
            value = random.gauss(self.current_value, std)
            return max(self.min_value, min(self.max_value, value))
        elif self.distribution == DistributionType.triangular:
            return random.triangular(self.min_value, self.current_value, self.max_value)
        return self.current_value


@dataclass
class Metric:
    """An outcome metric (e.g., project completion probability, fitness trend)."""
    name: str
    unit: str
    description: str
    target_value: Optional[float] = None


class GoalScenario:
    """A single scenario for a life goal with variables and outcome metrics."""
    
    def __init__(
        self,
        goal_id: str,
        goal_name: str,
        goal_category: GoalCategory,
        description: str,
        variables: dict[str, Variable],
        metrics: list[Metric],
        outcome_function: callable,  # (variables: dict) -> dict of metric_name -> value
        num_samples: int = 1000,
    ):
        self.goal_id = goal_id
        self.goal_name = goal_name
        self.goal_category = goal_category
        self.description = description
        self.variables = variables
        self.metrics = metrics
        self.outcome_function = outcome_function
        self.num_samples = num_samples
        
        self.samples: list[dict[str, float]] = []
        self.outcomes: list[dict[str, float]] = []
        self.statistics: dict[str, dict] = {}
    
    def run_simulation(self) -> None:
        """Run the Monte Carlo simulation."""
        self.samples = []
        self.outcomes = []
        
        logger.info(f"Running {self.num_samples} samples for scenario: {self.goal_name}")
        
        for _ in range(self.num_samples):
            # Sample all variables
            sample = {name: var.sample() for name, var in self.variables.items()}
            self.samples.append(sample)
            
            # Compute outcomes from this sample
            outcome = self.outcome_function(sample)
            self.outcomes.append(outcome)
        
        # Compute statistics
        self._compute_statistics()
        logger.info(f"Simulation complete for {self.goal_name}")
    
    def _compute_statistics(self) -> None:
        """Compute percentile statistics across all outcomes."""
        self.statistics = {}
        
        if not self.outcomes:
            return
        
        for metric in self.metrics:
            values = [o.get(metric.name, 0) for o in self.outcomes]
            values_sorted = sorted(values)
            
            # Manual percentile calculation
            def percentile(sorted_list, percent):
                k = (len(sorted_list) - 1) * percent / 100.0
                f = int(k)
                c = k - f
                if f + 1 < len(sorted_list):
                    return sorted_list[f] * (1 - c) + sorted_list[f + 1] * c
                return sorted_list[f]
            
            self.statistics[metric.name] = {
                "min": min(values),
                "p25": percentile(values_sorted, 25),
                "p50": percentile(values_sorted, 50),  # median
                "p75": percentile(values_sorted, 75),
                "max": max(values),
                "mean": statistics.mean(values),
                "stdev": statistics.stdev(values) if len(values) > 1 else 0,
            }
    
    def get_fan_chart(self, metric_name: str) -> dict[str, Any]:
        """Get fan chart data for a specific metric (min/p25/p50/p75/max over time)."""
        if metric_name not in self.statistics:
            return {}
        
        return {
            "metric": metric_name,
            "min": self.statistics[metric_name]["min"],
            "p25": self.statistics[metric_name]["p25"],
            "median": self.statistics[metric_name]["p50"],
            "p75": self.statistics[metric_name]["p75"],
            "max": self.statistics[metric_name]["max"],
            "mean": self.statistics[metric_name]["mean"],
            "stdev": self.statistics[metric_name]["stdev"],
        }
    
    def sensitivity_analysis(self) -> dict[str, float]:
        """Compute sensitivity of primary outcome to each variable.
        
        Returns correlation coefficient between each variable and primary outcome metric.
        """
        if not self.samples or not self.outcomes:
            return {}
        
        # Use first metric as primary outcome
        primary_metric = self.metrics[0].name if self.metrics else None
        if not primary_metric:
            return {}
        
        sensitivity = {}
        primary_values = [o.get(primary_metric, 0) for o in self.outcomes]
        
        # Compute mean and std for normalization
        primary_mean = statistics.mean(primary_values) if len(primary_values) > 0 else 0
        primary_stdev = statistics.stdev(primary_values) if len(primary_values) > 1 else 1
        
        for var_name, _ in self.variables.items():
            var_values = [s.get(var_name, 0) for s in self.samples]
            
            # Compute Pearson correlation manually
            if len(var_values) > 1:
                var_mean = statistics.mean(var_values)
                var_stdev = statistics.stdev(var_values)
                
                if var_stdev > 0 and primary_stdev > 0:
                    covariance = sum(
                        (v - var_mean) * (p - primary_mean)
                        for v, p in zip(var_values, primary_values)
                    ) / len(var_values)
                    
                    correlation = covariance / (var_stdev * primary_stdev)
                    sensitivity[var_name] = float(max(-1, min(1, correlation)))
                else:
                    sensitivity[var_name] = 0.0
            else:
                sensitivity[var_name] = 0.0
        
        return sensitivity
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize scenario to dict."""
        return {
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "goal_category": self.goal_category.value,
            "description": self.description,
            "variables": {
                name: {
                    "current": var.current_value,
                    "min": var.min_value,
                    "max": var.max_value,
                    "distribution": var.distribution.value,
                    "description": var.description,
                }
                for name, var in self.variables.items()
            },
            "metrics": [
                {
                    "name": m.name,
                    "unit": m.unit,
                    "description": m.description,
                    "target": m.target_value,
                }
                for m in self.metrics
            ],
            "statistics": self.statistics,
            "num_samples": self.num_samples,
        }


class ScenarioLibrary:
    """Pre-built scenario templates for common life goals."""
    
    @staticmethod
    def create_training_goal_scenario(
        current_hours_per_week: float,
        target_hours_per_week: float,
        weeks: int = 12,
    ) -> GoalScenario:
        """Training adherence scenario: weekly hours target vs actual."""
        
        def outcome_fn(vars: dict) -> dict:
            """Compute training outcomes."""
            weekly_hours = vars["weekly_hours"]
            adherence = vars["adherence_rate"]
            recovery_factor = vars["recovery_factor"]
            
            # Projected volume over period
            total_hours = weekly_hours * weeks * adherence * recovery_factor
            
            # Fitness improvement proxy (empirical: +5% per 100 hours)
            fitness_improvement = (total_hours / 100) * 5
            
            # Success: reached target hours 70% of the time
            success_prob = min(100, (weekly_hours / target_hours_per_week) * adherence * 100)
            
            return {
                "total_hours": total_hours,
                "fitness_improvement_pct": fitness_improvement,
                "success_probability": success_prob,
                "avg_weekly_hours": total_hours / weeks,
            }
        
        return GoalScenario(
            goal_id=str(uuid.uuid4()),
            goal_name=f"Training: {target_hours_per_week}h/week for {weeks} weeks",
            goal_category=GoalCategory.training,
            description=f"Can I sustain {target_hours_per_week} hours/week of training for {weeks} weeks?",
            variables={
                "weekly_hours": Variable(
                    name="weekly_hours",
                    current_value=current_hours_per_week,
                    min_value=max(0, current_hours_per_week * 0.5),
                    max_value=current_hours_per_week * 1.5,
                    distribution=DistributionType.normal,
                    std_dev=current_hours_per_week * 0.2,
                    description="Target weekly training hours",
                ),
                "adherence_rate": Variable(
                    name="adherence_rate",
                    current_value=0.75,
                    min_value=0.5,
                    max_value=1.0,
                    distribution=DistributionType.triangular,
                    description="Adherence to planned workouts (0-1)",
                ),
                "recovery_factor": Variable(
                    name="recovery_factor",
                    current_value=0.9,
                    min_value=0.7,
                    max_value=1.0,
                    distribution=DistributionType.normal,
                    std_dev=0.1,
                    description="Recovery efficiency multiplier",
                ),
            },
            metrics=[
                Metric("total_hours", "hours", "Total training hours over period"),
                Metric("fitness_improvement_pct", "%", "Estimated fitness improvement"),
                Metric("success_probability", "%", "Probability of achieving target"),
                Metric("avg_weekly_hours", "h/wk", "Average weekly hours"),
            ],
            outcome_function=outcome_fn,
            num_samples=1000,
        )
    
    @staticmethod
    def create_project_goal_scenario(
        project_size_hours: float,
        available_weekly_hours: float,
        risk_factor: float = 0.2,
    ) -> GoalScenario:
        """Project completion scenario: can I finish this project?"""
        
        def outcome_fn(vars: dict) -> dict:
            """Compute project outcomes."""
            weekly_hours = vars["weekly_available_hours"]
            completion_rate = vars["completion_rate"]
            risk = vars["scope_risk_factor"]
            
            # Adjusted project size based on risk
            adjusted_size = project_size_hours * (1 + risk)
            
            # Weeks to completion
            weeks_needed = adjusted_size / (weekly_hours * completion_rate) if weekly_hours > 0 else float('inf')
            
            # Success: complete within 6 months (26 weeks)
            success = 1.0 if weeks_needed <= 26 else max(0, 1 - (weeks_needed - 26) / 26)
            
            return {
                "weeks_to_completion": min(weeks_needed, 52),  # Cap at 1 year
                "adjusted_project_size": adjusted_size,
                "completion_probability": min(100, success * 100),
                "slack_weeks": max(0, 26 - weeks_needed),
            }
        
        return GoalScenario(
            goal_id=str(uuid.uuid4()),
            goal_name=f"Project: {project_size_hours}h completion",
            goal_category=GoalCategory.project,
            description=f"Can I complete a {project_size_hours}h project with {available_weekly_hours}h/week available?",
            variables={
                "weekly_available_hours": Variable(
                    name="weekly_available_hours",
                    current_value=available_weekly_hours,
                    min_value=available_weekly_hours * 0.5,
                    max_value=available_weekly_hours * 1.3,
                    distribution=DistributionType.normal,
                    std_dev=available_weekly_hours * 0.15,
                    description="Weekly hours available for project",
                ),
                "completion_rate": Variable(
                    name="completion_rate",
                    current_value=0.8,
                    min_value=0.5,
                    max_value=1.0,
                    distribution=DistributionType.triangular,
                    description="Task completion efficiency (0-1)",
                ),
                "scope_risk_factor": Variable(
                    name="scope_risk_factor",
                    current_value=risk_factor,
                    min_value=0.0,
                    max_value=0.5,
                    distribution=DistributionType.triangular,
                    description="Scope expansion risk (0-0.5 means 0-50% size growth)",
                ),
            },
            metrics=[
                Metric("weeks_to_completion", "weeks", "Weeks needed to complete"),
                Metric("completion_probability", "%", "Probability of 6-month completion"),
                Metric("adjusted_project_size", "hours", "Effective project size after risk adjustment"),
                Metric("slack_weeks", "weeks", "Weeks of slack buffer (26 - weeks_needed)"),
            ],
            outcome_function=outcome_fn,
            num_samples=1000,
        )
    
    @staticmethod
    def create_balance_goal_scenario(
        training_hours_week: float,
        project_hours_week: float,
        max_weekly_hours: float = 50,
    ) -> GoalScenario:
        """Life balance scenario: can I maintain both training and projects?"""
        
        def outcome_fn(vars: dict) -> dict:
            """Compute balance outcomes."""
            train = vars["training_hours"]
            project = vars["project_hours"]
            total_available = vars["total_available_hours"]
            stress_sensitivity = vars["stress_sensitivity"]
            
            # Total load
            total_load = train + project
            overload = max(0, total_load - total_available)
            load_ratio = total_load / total_available if total_available > 0 else 0
            
            # Stress impact (nonlinear)
            stress_score = min(100, 30 + (load_ratio - 1) * stress_sensitivity * 100)
            
            # Feasibility: both goals met AND stress < 70
            feasibility = 1.0 if (load_ratio <= 1.0 and stress_score < 70) else max(0, 1 - load_ratio)
            
            return {
                "total_load_hours": total_load,
                "load_ratio": load_ratio,
                "overload_hours": overload,
                "stress_score": stress_score,
                "feasibility_probability": feasibility * 100,
            }
        
        return GoalScenario(
            goal_id=str(uuid.uuid4()),
            goal_name="Life Balance",
            goal_category=GoalCategory.habits,
            description=f"Can I maintain {training_hours_week}h training + {project_hours_week}h projects?",
            variables={
                "training_hours": Variable(
                    name="training_hours",
                    current_value=training_hours_week,
                    min_value=max(0, training_hours_week * 0.7),
                    max_value=training_hours_week * 1.3,
                    distribution=DistributionType.normal,
                    std_dev=training_hours_week * 0.2,
                    description="Weekly training hours",
                ),
                "project_hours": Variable(
                    name="project_hours",
                    current_value=project_hours_week,
                    min_value=max(0, project_hours_week * 0.5),
                    max_value=project_hours_week * 1.5,
                    distribution=DistributionType.normal,
                    std_dev=project_hours_week * 0.25,
                    description="Weekly project hours",
                ),
                "total_available_hours": Variable(
                    name="total_available_hours",
                    current_value=max_weekly_hours,
                    min_value=max_weekly_hours * 0.85,
                    max_value=max_weekly_hours * 1.1,
                    distribution=DistributionType.normal,
                    std_dev=max_weekly_hours * 0.05,
                    description="Weekly hours available for discretionary activities",
                ),
                "stress_sensitivity": Variable(
                    name="stress_sensitivity",
                    current_value=1.0,
                    min_value=0.5,
                    max_value=2.0,
                    distribution=DistributionType.triangular,
                    description="How much load affects stress (personal sensitivity)",
                ),
            },
            metrics=[
                Metric("total_load_hours", "hours", "Total hours needed"),
                Metric("load_ratio", "ratio", "Load ratio (total / available)"),
                Metric("overload_hours", "hours", "Hours over available capacity"),
                Metric("stress_score", "points", "Estimated stress level (0-100)"),
                Metric("feasibility_probability", "%", "Probability of sustainable balance"),
            ],
            outcome_function=outcome_fn,
            num_samples=1000,
        )


# Pydantic models for API

class VariableInput(BaseModel):
    """Input model for a scenario variable."""
    name: str
    current_value: float
    min_value: float
    max_value: float
    distribution: DistributionType = DistributionType.normal
    std_dev: Optional[float] = None
    description: str = ""


class MetricInput(BaseModel):
    """Input model for an outcome metric."""
    name: str
    unit: str
    description: str
    target_value: Optional[float] = None


class ScenarioRequest(BaseModel):
    """Request to create and run a scenario."""
    goal_id: Optional[str] = None
    goal_name: str
    goal_category: GoalCategory
    description: str
    variables: dict[str, VariableInput]
    metrics: list[MetricInput]
    num_samples: int = Field(1000, ge=100, le=10000)


class FanChartData(BaseModel):
    """Fan chart response for a metric."""
    metric: str
    min: float
    p25: float
    median: float
    p75: float
    max: float
    mean: float
    stdev: float


class SensitivityAnalysis(BaseModel):
    """Sensitivity analysis: correlation of each variable to outcome."""
    variable_name: str
    correlation: float
    description: str = ""


class ScenarioResponse(BaseModel):
    """Response containing scenario results."""
    scenario_id: str
    goal_name: str
    goal_category: str
    description: str
    num_samples: int
    fan_charts: dict[str, FanChartData]
    sensitivity_analysis: list[SensitivityAnalysis]
    summary: dict[str, Any]
    recommendation: str
    
    class Config:
        arbitrary_types_allowed = True
