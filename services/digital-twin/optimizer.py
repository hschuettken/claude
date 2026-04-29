"""Auto-optimization loop for the digital twin.

Runs every hour, compares simulation scenarios vs baseline, and publishes a
recommendation when a non-baseline scenario saves >= SAVINGS_THRESHOLD EUR.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from .models import EnergyState, ScenarioID, SimulationReport, SimulationRequest, SCENARIO_LABELS
from .simulation import run_simulation

logger = logging.getLogger(__name__)

SAVINGS_THRESHOLD_EUR = 0.05  # only recommend when savings > 5 ct
OPTIMIZE_INTERVAL_S = 3600    # hourly

# Human-readable HA actions per scenario (informational — dashboard shows these)
_SCENARIO_ACTIONS: dict[str, list[dict[str, str]]] = {
    "B": [
        {
            "description": "Set battery to aggressive charge mode",
            "ha_service": "input_boolean.turn_on",
            "entity": "input_boolean.battery_aggressive_mode",
        }
    ],
    "C": [
        {
            "description": "Set EV charging to PV-surplus only",
            "ha_service": "input_select.select_option",
            "entity": "input_select.ev_charge_mode",
            "option": "pv_surplus",
        }
    ],
    "D": [
        {
            "description": "Enable pre-heat schedule (1–6 am extra 2 kW)",
            "ha_service": "input_boolean.turn_on",
            "entity": "input_boolean.homelab_preheat_enabled",
        }
    ],
}


@dataclass
class Recommendation:
    scenario_id: str
    scenario_name: str
    savings_eur: float
    best_sufficiency_pct: float
    baseline_cost_eur: float
    best_cost_eur: float
    actions: list[dict[str, str]]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "savings_eur": self.savings_eur,
            "best_sufficiency_pct": self.best_sufficiency_pct,
            "baseline_cost_eur": self.baseline_cost_eur,
            "best_cost_eur": self.best_cost_eur,
            "actions": self.actions,
            "generated_at": self.generated_at,
        }


_latest_recommendation: Optional[Recommendation] = None


def get_latest_recommendation() -> Optional[Recommendation]:
    return _latest_recommendation


def build_recommendation(report: SimulationReport) -> Optional[Recommendation]:
    """Return a Recommendation if any non-baseline scenario clears the savings threshold."""
    global _latest_recommendation

    if (
        report.savings_vs_baseline_eur is None
        or report.savings_vs_baseline_eur < SAVINGS_THRESHOLD_EUR
    ):
        return None

    best_id = report.best_cost_id
    if best_id is None or best_id == ScenarioID.A_BASELINE.value:
        return None

    baseline = next(
        (s for s in report.scenarios if s.scenario_id == ScenarioID.A_BASELINE), None
    )
    best = next(
        (s for s in report.scenarios if s.scenario_id.value == best_id), None
    )
    if baseline is None or best is None:
        return None

    rec = Recommendation(
        scenario_id=best_id,
        scenario_name=SCENARIO_LABELS.get(best.scenario_id, best_id),
        savings_eur=report.savings_vs_baseline_eur,
        best_sufficiency_pct=best.self_sufficiency_pct,
        baseline_cost_eur=baseline.energy_cost_eur,
        best_cost_eur=best.energy_cost_eur,
        actions=_SCENARIO_ACTIONS.get(best_id, []),
    )
    _latest_recommendation = rec
    return rec


async def run_optimizer_loop(
    get_energy_state: Callable[[], Awaitable[EnergyState]],
    get_pv_forecast: Callable[[float], Awaitable[list[float]]],
    publish: Callable[[str, dict[str, Any]], Awaitable[None]],
    **sim_kwargs: Any,
) -> None:
    """Long-running task: sleep 1 hour, run simulation, publish recommendation if warranted."""
    while True:
        await asyncio.sleep(OPTIMIZE_INTERVAL_S)
        try:
            energy = await get_energy_state()
            pv_forecast = await get_pv_forecast(energy.pv_total_power_w)
            report = run_simulation(
                request=SimulationRequest(),
                energy_state=energy,
                pv_forecast_kwh=pv_forecast,
                **sim_kwargs,
            )
            rec = build_recommendation(report)
            if rec:
                logger.info(
                    "optimizer_recommendation scenario=%s savings=%.2f eur",
                    rec.scenario_id,
                    rec.savings_eur,
                )
                await publish("digital.twin.recommendation", rec.to_dict())
            else:
                logger.info(
                    "optimizer_no_recommendation savings=%.4f threshold=%.2f",
                    report.savings_vs_baseline_eur or 0.0,
                    SAVINGS_THRESHOLD_EUR,
                )
        except Exception as exc:
            logger.warning("optimizer_loop_error error=%s", exc)
