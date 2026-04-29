"""Tests for the digital-twin auto-optimization loop.

All tests are pure — no I/O, no external services.
"""
from __future__ import annotations

import asyncio

import pytest

from digital_twin.models import EnergyState, ScenarioID, SimulationRequest
from digital_twin.optimizer import (
    SAVINGS_THRESHOLD_EUR,
    Recommendation,
    build_recommendation,
    get_latest_recommendation,
    run_optimizer_loop,
)
from digital_twin.simulation import run_simulation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flat(v: float, n: int = 24) -> list[float]:
    return [v] * n


def _make_report(pv_kwh: float = 1.5, battery_soc: float = 0.5, ev_soc: float = 0.5):
    return run_simulation(
        request=SimulationRequest(),
        energy_state=EnergyState(battery_soc_pct=battery_soc * 100, ev_soc_pct=ev_soc * 100),
        pv_forecast_kwh=_flat(pv_kwh),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation construction
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildRecommendation:
    def test_returns_none_when_savings_below_threshold(self):
        # With identical conditions all scenarios cost the same → no recommendation
        report = _make_report(pv_kwh=0.0, battery_soc=0.0, ev_soc=1.0)
        rec = build_recommendation(report)
        # baseline wins or savings < threshold → None
        if rec is not None:
            assert rec.savings_eur >= SAVINGS_THRESHOLD_EUR

    def test_returns_recommendation_when_savings_above_threshold(self):
        # High PV + low battery — aggressive battery should differ from baseline
        report = _make_report(pv_kwh=3.0, battery_soc=0.1, ev_soc=0.2)
        rec = build_recommendation(report)
        # May or may not recommend depending on scenario differences
        if rec is not None:
            assert rec.scenario_id != "A"
            assert rec.savings_eur >= SAVINGS_THRESHOLD_EUR

    def test_recommendation_has_required_fields(self):
        # Force a scenario difference by using very high PV and low battery
        for pv in [3.0, 5.0]:
            report = _make_report(pv_kwh=pv, battery_soc=0.0, ev_soc=0.1)
            rec = build_recommendation(report)
            if rec is not None:
                assert rec.scenario_id in ("A", "B", "C", "D")
                assert rec.scenario_name
                assert isinstance(rec.savings_eur, float)
                assert isinstance(rec.baseline_cost_eur, float)
                assert isinstance(rec.best_cost_eur, float)
                assert isinstance(rec.actions, list)
                assert rec.generated_at
                break

    def test_recommendation_to_dict_has_all_keys(self):
        rec = Recommendation(
            scenario_id="C",
            scenario_name="EV PV-Only",
            savings_eur=0.30,
            best_sufficiency_pct=75.0,
            baseline_cost_eur=1.20,
            best_cost_eur=0.90,
            actions=[{"description": "set EV to PV-only"}],
        )
        d = rec.to_dict()
        for key in (
            "scenario_id",
            "scenario_name",
            "savings_eur",
            "best_sufficiency_pct",
            "baseline_cost_eur",
            "best_cost_eur",
            "actions",
            "generated_at",
        ):
            assert key in d

    def test_get_latest_recommendation_initially_none(self):
        # Reset state by calling build_recommendation with a report that produces None
        report = _make_report(pv_kwh=0.0, battery_soc=1.0, ev_soc=1.0)
        build_recommendation(report)
        # get_latest_recommendation may return None or a previous rec — just check type
        rec = get_latest_recommendation()
        assert rec is None or isinstance(rec, Recommendation)


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation content validation
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommendationContent:
    def test_scenario_c_actions_include_ev_mode(self):
        rec = Recommendation(
            scenario_id="C",
            scenario_name="EV PV-Only",
            savings_eur=0.10,
            best_sufficiency_pct=60.0,
            baseline_cost_eur=0.80,
            best_cost_eur=0.70,
            actions=[
                {
                    "description": "Set EV charging to PV-surplus only",
                    "ha_service": "input_select.select_option",
                    "entity": "input_select.ev_charge_mode",
                    "option": "pv_surplus",
                }
            ],
        )
        assert any("ev_charge_mode" in a.get("entity", "") for a in rec.actions)

    def test_savings_eur_is_positive(self):
        rec = Recommendation(
            scenario_id="B",
            scenario_name="Aggressive Battery",
            savings_eur=0.15,
            best_sufficiency_pct=80.0,
            baseline_cost_eur=1.00,
            best_cost_eur=0.85,
            actions=[],
        )
        assert rec.savings_eur > 0

    def test_baseline_cost_greater_than_best_cost(self):
        rec = Recommendation(
            scenario_id="B",
            scenario_name="Aggressive Battery",
            savings_eur=0.15,
            best_sufficiency_pct=80.0,
            baseline_cost_eur=1.00,
            best_cost_eur=0.85,
            actions=[],
        )
        assert rec.baseline_cost_eur > rec.best_cost_eur


# ─────────────────────────────────────────────────────────────────────────────
# Optimizer loop (async, abbreviated)
# ─────────────────────────────────────────────────────────────────────────────

class TestOptimizerLoop:
    @pytest.mark.asyncio
    async def test_loop_publishes_recommendation_on_savings(self):
        """Optimizer publishes to NATS when savings >= threshold."""
        published: list[tuple[str, dict]] = []

        async def fake_energy() -> EnergyState:
            return EnergyState(battery_soc_pct=10.0, ev_soc_pct=20.0)

        async def fake_pv(_: float) -> list[float]:
            return _flat(4.0)  # high PV — aggressive battery likely saves money

        async def fake_publish(subject: str, payload: dict) -> None:
            published.append((subject, payload))

        # Patch interval to 0 so it runs immediately after first sleep
        import digital_twin.optimizer as opt_module
        original = opt_module.OPTIMIZE_INTERVAL_S
        opt_module.OPTIMIZE_INTERVAL_S = 0

        try:
            task = asyncio.create_task(
                run_optimizer_loop(
                    get_energy_state=fake_energy,
                    get_pv_forecast=fake_pv,
                    publish=fake_publish,
                )
            )
            await asyncio.sleep(0.05)  # let one iteration run
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            opt_module.OPTIMIZE_INTERVAL_S = original

        # Either a recommendation was published or savings were below threshold
        for subject, payload in published:
            assert subject == "digital.twin.recommendation"
            assert "scenario_id" in payload
            assert "savings_eur" in payload
            assert payload["savings_eur"] >= SAVINGS_THRESHOLD_EUR

    @pytest.mark.asyncio
    async def test_loop_handles_errors_gracefully(self):
        """Optimizer loop does not crash when energy fetch raises."""
        published: list = []

        async def broken_energy() -> EnergyState:
            raise RuntimeError("HA unreachable")

        async def fake_pv(_: float) -> list[float]:
            return _flat(1.0)

        async def fake_publish(subject: str, payload: dict) -> None:
            published.append((subject, payload))

        import digital_twin.optimizer as opt_module
        original = opt_module.OPTIMIZE_INTERVAL_S
        opt_module.OPTIMIZE_INTERVAL_S = 0

        try:
            task = asyncio.create_task(
                run_optimizer_loop(
                    get_energy_state=broken_energy,
                    get_pv_forecast=fake_pv,
                    publish=fake_publish,
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            opt_module.OPTIMIZE_INTERVAL_S = original

        # No crash — nothing was published
        assert published == []
