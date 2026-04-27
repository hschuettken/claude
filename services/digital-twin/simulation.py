"""Scenario simulation engine for the Digital Twin.

Simulates 4 energy management scenarios over a 24-hour horizon using
the current house state and a PV production forecast. All logic is pure
(no I/O) so it can be tested without any external services.

Scenarios:
  A — Baseline: battery opportunistically charged from PV surplus
  B — Aggressive battery: fully charge battery whenever PV available,
      discharge during evening peak (18–22h) regardless of PV
  C — EV PV-only: EV only charges when PV surplus > min_charge_power
  D — Pre-heat: extra heating during low-demand hours (1–6) to reduce
      heating demand during busier periods
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    EnergyState,
    HourlyResult,
    ScenarioID,
    ScenarioResult,
    SimulationReport,
    SimulationRequest,
    SCENARIO_LABELS,
)

# Typical hourly house consumption fraction (relative, no EV or extra heating).
# Shape adapted from German household usage patterns.
# Values are kWh/hour at 0.45 kWh/h daily average.
_HOUSE_PROFILE: list[float] = [
    0.25, 0.22, 0.20, 0.20, 0.22, 0.28,  # 00–05  night → early morning
    0.40, 0.60, 0.55, 0.48, 0.45, 0.44,  # 06–11  morning
    0.44, 0.43, 0.43, 0.44, 0.50, 0.60,  # 12–17  afternoon → early evening
    0.70, 0.72, 0.65, 0.55, 0.42, 0.30,  # 18–23  evening
]

# EV charging profile for Scenario A/B/D: charge mostly overnight and in morning
_EV_PROFILE_DEFAULT: list[float] = [
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,   # 00–05  off (battery-prefer hours)
    1.0, 1.0, 1.0, 1.0, 1.0, 1.0,   # 06–11  morning charge (if needed)
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,   # 12–17  off (PV hours — battery priority)
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,   # 18–23  off
]


@dataclass
class SimParams:
    """Parameters for one simulation run (derived from settings + request)."""
    pv_forecast_kwh: list[float]        # 24 values
    battery_soc_init: float             # 0.0–1.0
    battery_cap_kwh: float = 7.0
    battery_max_kw: float = 3.5
    battery_efficiency: float = 0.95   # round-trip per half
    ev_soc_init_pct: float = 50.0
    ev_cap_kwh: float = 83.0
    ev_target_kwh: float = 20.0        # extra kWh to charge
    ev_min_power_kw: float = 1.4
    ev_max_power_kw: float = 11.0
    ev_departure_hour: int = 7
    house_profile: list[float] = field(default_factory=lambda: _HOUSE_PROFILE.copy())
    tariff_import_ct: float = 25.0
    tariff_export_ct: float = 7.0
    preheat_power_kw: float = 2.0
    preheat_hours: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])


# ─────────────────────────────────────────────────────────────────────────────
# Core hourly balance
# ─────────────────────────────────────────────────────────────────────────────

def _hour_balance(
    pv_kwh: float,
    house_kwh: float,
    ev_kwh: float,
    extra_heat_kwh: float,
    battery_soc: float,       # current state (0–1)
    battery_cap: float,
    battery_max_kw: float,
    efficiency: float,
    aggressive_discharge: bool = False,
) -> tuple[float, float, float, float, float]:
    """Compute grid flows and new battery SoC for one hour.

    Returns:
        (grid_import_kwh, grid_export_kwh, battery_delta_kwh,
         new_battery_soc, battery_cycles_increment)
    """
    total_load = house_kwh + ev_kwh + extra_heat_kwh
    net = pv_kwh - total_load    # positive = surplus

    battery_delta = 0.0  # positive = charging
    grid_import = 0.0
    grid_export = 0.0

    if net >= 0:
        # PV surplus — charge battery first
        available_to_charge = battery_cap * (1.0 - battery_soc)
        charge = min(net, battery_max_kw, available_to_charge)
        battery_soc = min(1.0, battery_soc + charge * efficiency / battery_cap)
        battery_delta = charge
        remaining_surplus = net - charge
        grid_export = remaining_surplus
    else:
        # PV deficit — discharge battery
        deficit = abs(net)
        available_to_discharge = battery_cap * battery_soc * efficiency
        discharge = min(deficit, battery_max_kw, available_to_discharge)
        battery_soc = max(0.0, battery_soc - discharge / efficiency / battery_cap)
        battery_delta = -discharge
        remaining_deficit = deficit - discharge
        grid_import = remaining_deficit

    # Aggressive discharge during evening (18–22): push battery to grid even if no deficit
    if aggressive_discharge and battery_soc > 0.1 and net >= 0:
        extra_discharge = min(battery_max_kw * 0.5, battery_cap * battery_soc * 0.3)
        battery_soc = max(0.0, battery_soc - extra_discharge / efficiency / battery_cap)
        battery_delta -= extra_discharge
        grid_export += extra_discharge

    # Cycle counting: half a full cycle per kWh charged or discharged
    cycles_inc = abs(battery_delta) / (2.0 * battery_cap) if battery_cap > 0 else 0.0

    return grid_import, grid_export, battery_delta, battery_soc, cycles_inc


# ─────────────────────────────────────────────────────────────────────────────
# Per-scenario hourly EV / heating overrides
# ─────────────────────────────────────────────────────────────────────────────

def _ev_kwh_baseline(
    hour: int,
    ev_remaining_kwh: float,
    ev_max_kw: float,
    ev_departure_hour: int,
) -> tuple[float, float]:
    """Scenario A/B: charge EV in morning before departure."""
    if ev_remaining_kwh <= 0 or hour >= ev_departure_hour:
        return 0.0, ev_remaining_kwh
    if _EV_PROFILE_DEFAULT[hour] == 0.0:
        return 0.0, ev_remaining_kwh
    charge = min(ev_max_kw, ev_remaining_kwh)
    return charge, max(0.0, ev_remaining_kwh - charge)


def _ev_kwh_pv_only(
    hour: int,
    pv_kwh: float,
    house_kwh: float,
    ev_remaining_kwh: float,
    ev_min_kw: float,
    ev_max_kw: float,
) -> tuple[float, float]:
    """Scenario C: EV only charges from PV surplus."""
    surplus = pv_kwh - house_kwh
    if surplus < ev_min_kw or ev_remaining_kwh <= 0:
        return 0.0, ev_remaining_kwh
    charge = min(surplus, ev_max_kw, ev_remaining_kwh)
    return charge, max(0.0, ev_remaining_kwh - charge)


def _heating_extra_kwh(scenario: ScenarioID, hour: int, preheat_hours: list[int], preheat_kw: float) -> float:
    """Scenario D: extra heating energy during low-demand hours."""
    if scenario == ScenarioID.D_PREHEAT and hour in preheat_hours:
        return preheat_kw
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Scenario simulation
# ─────────────────────────────────────────────────────────────────────────────

def simulate_scenario(scenario: ScenarioID, params: SimParams) -> ScenarioResult:
    battery_soc = min(1.0, max(0.0, params.battery_soc_init))
    ev_remaining_kwh = params.ev_target_kwh
    total_grid_import = 0.0
    total_grid_export = 0.0
    total_cycles = 0.0
    total_ev_charged = 0.0
    hourly: list[HourlyResult] = []

    for hour in range(len(params.pv_forecast_kwh)):
        pv_kwh = params.pv_forecast_kwh[hour]
        house_kwh = params.house_profile[hour % 24]

        # EV charging
        if scenario == ScenarioID.C_EV_PV_ONLY:
            ev_kwh, ev_remaining_kwh = _ev_kwh_pv_only(
                hour, pv_kwh, house_kwh, ev_remaining_kwh,
                params.ev_min_power_kw, params.ev_max_power_kw,
            )
        else:
            ev_kwh, ev_remaining_kwh = _ev_kwh_baseline(
                hour, ev_remaining_kwh, params.ev_max_power_kw, params.ev_departure_hour
            )

        # Extra heating
        extra_heat = _heating_extra_kwh(scenario, hour, params.preheat_hours, params.preheat_power_kw)

        # Battery aggressiveness
        aggressive_discharge = (
            scenario == ScenarioID.B_AGGRESSIVE_BATTERY and 18 <= hour <= 22
        )

        grid_import, grid_export, battery_delta, battery_soc, cycles_inc = _hour_balance(
            pv_kwh=pv_kwh,
            house_kwh=house_kwh,
            ev_kwh=ev_kwh,
            extra_heat_kwh=extra_heat,
            battery_soc=battery_soc,
            battery_cap=params.battery_cap_kwh,
            battery_max_kw=params.battery_max_kw,
            efficiency=params.battery_efficiency,
            aggressive_discharge=aggressive_discharge,
        )

        total_grid_import += grid_import
        total_grid_export += grid_export
        total_cycles += cycles_inc
        total_ev_charged += ev_kwh

        hourly.append(
            HourlyResult(
                hour=hour,
                pv_kwh=round(pv_kwh, 4),
                house_kwh=round(house_kwh, 4),
                ev_kwh=round(ev_kwh, 4),
                heating_extra_kwh=round(extra_heat, 4),
                battery_delta_kwh=round(battery_delta, 4),
                grid_import_kwh=round(grid_import, 4),
                grid_export_kwh=round(grid_export, 4),
                battery_soc_pct=round(battery_soc * 100, 1),
            )
        )

    total_consumption = sum(
        params.house_profile[h % 24]
        + (hourly[h].ev_kwh if h < len(hourly) else 0)
        + (hourly[h].heating_extra_kwh if h < len(hourly) else 0)
        for h in range(len(params.pv_forecast_kwh))
    )
    self_sufficiency = (
        (1.0 - total_grid_import / total_consumption) * 100.0
        if total_consumption > 0
        else 100.0
    )
    energy_cost = (
        total_grid_import * params.tariff_import_ct / 100.0
        - total_grid_export * params.tariff_export_ct / 100.0
    )

    # Comfort score: penalise pre-heat (scenario D raises setpoint unnecessarily in
    # summer) and EV-PV-only (may leave EV under-charged at departure).
    comfort = 90.0
    if scenario == ScenarioID.D_PREHEAT:
        comfort = 80.0  # slight overheating risk
    if scenario == ScenarioID.C_EV_PV_ONLY:
        ev_charged_pct = total_ev_charged / params.ev_target_kwh if params.ev_target_kwh > 0 else 1.0
        comfort = min(90.0, 60.0 + ev_charged_pct * 30.0)

    return ScenarioResult(
        scenario_id=scenario,
        scenario_name=SCENARIO_LABELS[scenario],
        grid_import_kwh=round(total_grid_import, 3),
        grid_export_kwh=round(total_grid_export, 3),
        energy_cost_eur=round(energy_cost, 4),
        self_sufficiency_pct=round(max(0.0, min(100.0, self_sufficiency)), 1),
        battery_cycles=round(total_cycles, 4),
        ev_charged_kwh=round(total_ev_charged, 3),
        comfort_score=round(comfort, 1),
        hourly=hourly,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(
    request: SimulationRequest,
    energy_state: EnergyState,
    pv_forecast_kwh: list[float],
    battery_cap_kwh: float = 7.0,
    battery_max_kw: float = 3.5,
    ev_cap_kwh: float = 83.0,
    ev_min_power_kw: float = 1.4,
    ev_max_power_kw: float = 11.0,
    tariff_import_ct: float = 25.0,
    tariff_export_ct: float = 7.0,
    preheat_power_kw: float = 2.0,
    preheat_hours: Optional[list[int]] = None,
) -> SimulationReport:
    """Run all requested scenarios and return a SimulationReport."""
    if preheat_hours is None:
        preheat_hours = [1, 2, 3, 4, 5]

    horizon = min(request.horizon_hours, len(pv_forecast_kwh))
    forecast = pv_forecast_kwh[:horizon]
    # Pad to horizon if forecast is shorter
    while len(forecast) < horizon:
        forecast.append(0.0)

    ev_target = request.ev_target_kwh
    if ev_target is None:
        # Default: fill to 80% from current SoC
        current_soc = energy_state.ev_soc_pct or 50.0
        ev_target = max(0.0, (80.0 - current_soc) / 100.0 * ev_cap_kwh)

    params = SimParams(
        pv_forecast_kwh=forecast,
        battery_soc_init=energy_state.battery_soc_pct / 100.0,
        battery_cap_kwh=battery_cap_kwh,
        battery_max_kw=battery_max_kw,
        ev_soc_init_pct=energy_state.ev_soc_pct or 50.0,
        ev_cap_kwh=ev_cap_kwh,
        ev_target_kwh=ev_target,
        ev_min_power_kw=ev_min_power_kw,
        ev_max_power_kw=ev_max_power_kw,
        ev_departure_hour=request.ev_departure_hour,
        tariff_import_ct=tariff_import_ct,
        tariff_export_ct=tariff_export_ct,
        preheat_power_kw=preheat_power_kw,
        preheat_hours=preheat_hours,
    )

    results: list[ScenarioResult] = []
    for scenario_id in request.scenarios:
        result = simulate_scenario(scenario_id, params)
        results.append(result)

    # Find best scenarios
    best_cost_id: Optional[ScenarioID] = None
    best_suff_id: Optional[ScenarioID] = None
    baseline_cost: Optional[float] = None

    for r in results:
        if r.scenario_id == ScenarioID.A_BASELINE:
            baseline_cost = r.energy_cost_eur
        if best_cost_id is None or r.energy_cost_eur < next(
            (x.energy_cost_eur for x in results if x.scenario_id == best_cost_id), float("inf")
        ):
            best_cost_id = r.scenario_id
        if best_suff_id is None or r.self_sufficiency_pct > next(
            (x.self_sufficiency_pct for x in results if x.scenario_id == best_suff_id), -1.0
        ):
            best_suff_id = r.scenario_id

    savings = None
    if baseline_cost is not None and best_cost_id is not None:
        best_cost = next(r.energy_cost_eur for r in results if r.scenario_id == best_cost_id)
        savings = round(baseline_cost - best_cost, 4)

    return SimulationReport(
        horizon_hours=horizon,
        scenarios=results,
        baseline_id=ScenarioID.A_BASELINE,
        best_cost_id=best_cost_id,
        best_sufficiency_id=best_suff_id,
        savings_vs_baseline_eur=savings,
    )
