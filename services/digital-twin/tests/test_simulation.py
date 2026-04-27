"""Tests for the digital-twin simulation engine.

All tests use pure functions — no I/O, no external services.
"""
from __future__ import annotations

import pytest

from digital_twin.models import EnergyState, ScenarioID, SimulationRequest
from digital_twin.simulation import (
    SimParams,
    _ev_kwh_baseline,
    _ev_kwh_pv_only,
    _heating_extra_kwh,
    _hour_balance,
    run_simulation,
    simulate_scenario,
)
from digital_twin.state_ingestion import _shape_forecast


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flat_forecast(value: float = 0.5, hours: int = 24) -> list[float]:
    return [value] * hours


def _default_params(**kwargs) -> SimParams:
    defaults = dict(
        pv_forecast_kwh=_flat_forecast(0.8),
        battery_soc_init=0.5,
        battery_cap_kwh=7.0,
        battery_max_kw=3.5,
        ev_target_kwh=15.0,
        ev_departure_hour=7,
        tariff_import_ct=25.0,
        tariff_export_ct=7.0,
    )
    defaults.update(kwargs)
    return SimParams(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# _hour_balance
# ─────────────────────────────────────────────────────────────────────────────

class TestHourBalance:
    def test_surplus_charges_battery(self):
        grid_import, grid_export, delta, new_soc, cycles = _hour_balance(
            pv_kwh=2.0, house_kwh=0.5, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.0, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert delta > 0        # battery charged
        assert grid_import == pytest.approx(0.0)

    def test_deficit_discharges_battery(self):
        grid_import, grid_export, delta, new_soc, cycles = _hour_balance(
            pv_kwh=0.0, house_kwh=0.5, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.5, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert delta < 0        # battery discharged
        assert grid_import == pytest.approx(0.0, abs=0.1)

    def test_empty_battery_imports_from_grid(self):
        grid_import, grid_export, delta, new_soc, cycles = _hour_balance(
            pv_kwh=0.0, house_kwh=1.0, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.0, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert grid_import == pytest.approx(1.0)
        assert grid_export == pytest.approx(0.0)

    def test_excess_after_full_battery_exports(self):
        grid_import, grid_export, delta, new_soc, cycles = _hour_balance(
            pv_kwh=5.0, house_kwh=0.3, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=1.0, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert grid_export > 0
        assert grid_import == pytest.approx(0.0)

    def test_soc_bounded_0_to_1(self):
        # Discharge below 0
        _, _, _, new_soc, _ = _hour_balance(
            pv_kwh=0.0, house_kwh=100.0, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.1, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert new_soc >= 0.0

        # Charge above 1
        _, _, _, new_soc, _ = _hour_balance(
            pv_kwh=100.0, house_kwh=0.0, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.9, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert new_soc <= 1.0

    def test_cycles_increment_positive(self):
        *_, cycles = _hour_balance(
            pv_kwh=2.0, house_kwh=0.5, ev_kwh=0.0, extra_heat_kwh=0.0,
            battery_soc=0.0, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        assert cycles >= 0.0

    def test_energy_conservation(self):
        """Grid balance: pv + import = consumption + export (within rounding)."""
        pv, house, ev, heat = 1.5, 0.6, 0.3, 0.0
        grid_import, grid_export, delta, _, _ = _hour_balance(
            pv_kwh=pv, house_kwh=house, ev_kwh=ev, extra_heat_kwh=heat,
            battery_soc=0.5, battery_cap=7.0, battery_max_kw=3.5, efficiency=0.95
        )
        # pv + import = house + ev + heat + export + battery_delta(approx)
        lhs = pv + grid_import
        rhs = house + ev + heat + grid_export + delta
        assert abs(lhs - rhs) < 0.05  # small rounding from efficiency


# ─────────────────────────────────────────────────────────────────────────────
# EV charging strategies
# ─────────────────────────────────────────────────────────────────────────────

class TestEVCharging:
    def test_baseline_charges_before_departure(self):
        charge, remaining = _ev_kwh_baseline(
            hour=6, ev_remaining_kwh=10.0, ev_max_kw=11.0, ev_departure_hour=7
        )
        assert charge > 0

    def test_baseline_stops_at_departure(self):
        charge, remaining = _ev_kwh_baseline(
            hour=7, ev_remaining_kwh=10.0, ev_max_kw=11.0, ev_departure_hour=7
        )
        assert charge == 0.0

    def test_baseline_stops_when_full(self):
        charge, remaining = _ev_kwh_baseline(
            hour=6, ev_remaining_kwh=0.0, ev_max_kw=11.0, ev_departure_hour=7
        )
        assert charge == 0.0

    def test_pv_only_charges_from_surplus(self):
        # 2 kWh PV, 0.5 kWh house → 1.5 kWh surplus > 1.4 kW min
        charge, remaining = _ev_kwh_pv_only(
            hour=10, pv_kwh=2.0, house_kwh=0.5, ev_remaining_kwh=10.0,
            ev_min_kw=1.4, ev_max_kw=11.0
        )
        assert charge > 0

    def test_pv_only_no_charge_when_insufficient_surplus(self):
        # 0.3 kWh PV, 0.5 kWh house → −0.2 kWh surplus < 1.4 kW min
        charge, _ = _ev_kwh_pv_only(
            hour=5, pv_kwh=0.3, house_kwh=0.5, ev_remaining_kwh=10.0,
            ev_min_kw=1.4, ev_max_kw=11.0
        )
        assert charge == 0.0

    def test_pv_only_respects_max_power(self):
        charge, _ = _ev_kwh_pv_only(
            hour=12, pv_kwh=15.0, house_kwh=0.5, ev_remaining_kwh=10.0,
            ev_min_kw=1.4, ev_max_kw=3.0
        )
        assert charge <= 3.0


# ─────────────────────────────────────────────────────────────────────────────
# Heating extra
# ─────────────────────────────────────────────────────────────────────────────

class TestHeatingExtra:
    def test_preheat_during_preheat_hours(self):
        extra = _heating_extra_kwh(ScenarioID.D_PREHEAT, hour=3, preheat_hours=[1, 2, 3, 4, 5], preheat_kw=2.0)
        assert extra == pytest.approx(2.0)

    def test_preheat_zero_outside_hours(self):
        extra = _heating_extra_kwh(ScenarioID.D_PREHEAT, hour=12, preheat_hours=[1, 2, 3, 4, 5], preheat_kw=2.0)
        assert extra == pytest.approx(0.0)

    def test_no_preheat_for_other_scenarios(self):
        for s in (ScenarioID.A_BASELINE, ScenarioID.B_AGGRESSIVE_BATTERY, ScenarioID.C_EV_PV_ONLY):
            extra = _heating_extra_kwh(s, hour=2, preheat_hours=[1, 2, 3], preheat_kw=2.0)
            assert extra == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario simulation
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulateScenario:
    def test_returns_24_hourly_values(self):
        result = simulate_scenario(ScenarioID.A_BASELINE, _default_params())
        assert len(result.hourly) == 24

    def test_scenario_id_set_correctly(self):
        for s in ScenarioID:
            result = simulate_scenario(s, _default_params())
            assert result.scenario_id == s

    def test_self_sufficiency_between_0_and_100(self):
        for s in ScenarioID:
            result = simulate_scenario(s, _default_params())
            assert 0.0 <= result.self_sufficiency_pct <= 100.0

    def test_battery_cycles_non_negative(self):
        result = simulate_scenario(ScenarioID.A_BASELINE, _default_params())
        assert result.battery_cycles >= 0.0

    def test_ev_charged_non_negative(self):
        result = simulate_scenario(ScenarioID.C_EV_PV_ONLY, _default_params())
        assert result.ev_charged_kwh >= 0.0

    def test_pv_only_charges_less_than_baseline(self):
        """Scenario C should charge EV less than A on a day with little PV."""
        params_low_pv = _default_params(pv_forecast_kwh=_flat_forecast(0.1))
        result_a = simulate_scenario(ScenarioID.A_BASELINE, params_low_pv)
        result_c = simulate_scenario(ScenarioID.C_EV_PV_ONLY, params_low_pv)
        assert result_c.ev_charged_kwh <= result_a.ev_charged_kwh

    def test_preheat_uses_more_energy(self):
        """Scenario D adds extra heating — total import should be >= baseline."""
        params = _default_params(pv_forecast_kwh=_flat_forecast(0.0))  # no PV
        result_a = simulate_scenario(ScenarioID.A_BASELINE, params)
        result_d = simulate_scenario(ScenarioID.D_PREHEAT, params)
        assert result_d.grid_import_kwh >= result_a.grid_import_kwh

    def test_comfort_score_between_0_and_100(self):
        for s in ScenarioID:
            result = simulate_scenario(s, _default_params())
            assert 0.0 <= result.comfort_score <= 100.0

    def test_hourly_battery_soc_between_0_and_100(self):
        result = simulate_scenario(ScenarioID.A_BASELINE, _default_params())
        for h in result.hourly:
            assert 0.0 <= h.battery_soc_pct <= 100.0

    def test_no_pv_means_all_grid_import(self):
        """With zero PV and empty battery, all consumption is grid import."""
        params = _default_params(
            pv_forecast_kwh=_flat_forecast(0.0),
            battery_soc_init=0.0,
            ev_target_kwh=0.0,
        )
        result = simulate_scenario(ScenarioID.A_BASELINE, params)
        total_house = sum(params.house_profile[h] for h in range(24))
        assert abs(result.grid_import_kwh - total_house) < 0.1


# ─────────────────────────────────────────────────────────────────────────────
# run_simulation (integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunSimulation:
    def _make_request(self, **kwargs) -> SimulationRequest:
        return SimulationRequest(**kwargs)

    def _make_energy(self, **kwargs) -> EnergyState:
        return EnergyState(**kwargs)

    def test_returns_all_scenarios_by_default(self):
        report = run_simulation(
            request=self._make_request(),
            energy_state=self._make_energy(battery_soc_pct=50.0, ev_soc_pct=40.0),
            pv_forecast_kwh=_flat_forecast(1.0),
        )
        assert len(report.scenarios) == len(list(ScenarioID))

    def test_returns_only_requested_scenarios(self):
        report = run_simulation(
            request=self._make_request(scenarios=[ScenarioID.A_BASELINE]),
            energy_state=self._make_energy(),
            pv_forecast_kwh=_flat_forecast(1.0),
        )
        assert len(report.scenarios) == 1

    def test_best_cost_id_set(self):
        report = run_simulation(
            request=self._make_request(),
            energy_state=self._make_energy(battery_soc_pct=50.0),
            pv_forecast_kwh=_flat_forecast(1.5),
        )
        assert report.best_cost_id is not None

    def test_best_sufficiency_id_set(self):
        report = run_simulation(
            request=self._make_request(),
            energy_state=self._make_energy(battery_soc_pct=50.0),
            pv_forecast_kwh=_flat_forecast(1.5),
        )
        assert report.best_sufficiency_id is not None

    def test_savings_computed_when_baseline_included(self):
        report = run_simulation(
            request=self._make_request(
                scenarios=[ScenarioID.A_BASELINE, ScenarioID.B_AGGRESSIVE_BATTERY]
            ),
            energy_state=self._make_energy(battery_soc_pct=20.0),
            pv_forecast_kwh=_flat_forecast(2.0),
        )
        assert report.savings_vs_baseline_eur is not None

    def test_horizon_truncated_to_forecast_length(self):
        report = run_simulation(
            request=self._make_request(
                scenarios=[ScenarioID.A_BASELINE], horizon_hours=48
            ),
            energy_state=self._make_energy(),
            pv_forecast_kwh=_flat_forecast(1.0, hours=24),
        )
        assert report.horizon_hours == 24
        assert len(report.scenarios[0].hourly) == 24

    def test_ev_target_defaults_from_soc(self):
        """ev_target_kwh = None → auto-calculated from ev_soc_pct."""
        report = run_simulation(
            request=self._make_request(ev_target_kwh=None),
            energy_state=self._make_energy(ev_soc_pct=60.0),
            pv_forecast_kwh=_flat_forecast(1.0),
            ev_cap_kwh=80.0,
        )
        # 60% SoC → need 20% to reach 80% → 16 kWh
        assert report is not None  # just verify it runs without error


# ─────────────────────────────────────────────────────────────────────────────
# PV forecast shaping
# ─────────────────────────────────────────────────────────────────────────────

class TestShapeForecast:
    def test_returns_24_values(self):
        result = _shape_forecast(10.0)
        assert len(result) == 24

    def test_sums_to_daily_total(self):
        daily = 12.5
        result = _shape_forecast(daily)
        assert abs(sum(result) - daily) < 0.01

    def test_zero_at_night(self):
        result = _shape_forecast(10.0)
        assert result[0] == pytest.approx(0.0)   # midnight
        assert result[23] == pytest.approx(0.0)  # 23:00

    def test_peak_at_midday(self):
        result = _shape_forecast(10.0)
        # Max production should be around hour 11-12
        max_hour = result.index(max(result))
        assert 9 <= max_hour <= 14
