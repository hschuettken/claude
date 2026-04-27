"""Pydantic models for the Digital Twin service."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# House state
# ─────────────────────────────────────────────────────────────────────────────

class RoomState(BaseModel):
    room_id: str
    name: str
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    occupancy: Optional[bool] = None
    heating_on: Optional[bool] = None
    entities: list[str] = Field(default_factory=list)


class EnergyState(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pv_east_power_w: float = 0.0
    pv_west_power_w: float = 0.0
    pv_total_power_w: float = 0.0
    battery_soc_pct: float = 0.0
    battery_power_w: float = 0.0   # positive = charging, negative = discharging
    grid_power_w: float = 0.0      # positive = exporting, negative = importing
    house_consumption_w: float = 0.0
    ev_charging_w: float = 0.0
    ev_soc_pct: Optional[float] = None

    @property
    def pv_total_kw(self) -> float:
        return self.pv_total_power_w / 1000

    @property
    def grid_importing(self) -> bool:
        return self.grid_power_w < 0


class HouseState(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rooms: dict[str, RoomState] = Field(default_factory=dict)
    energy: EnergyState = Field(default_factory=EnergyState)
    safe_mode: bool = False
    data_source: str = "ha"


# ─────────────────────────────────────────────────────────────────────────────
# Room registry (persistent config)
# ─────────────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    floor: Optional[str] = None
    area_m2: Optional[float] = None
    ha_temperature_entity: Optional[str] = None
    ha_humidity_entity: Optional[str] = None
    ha_occupancy_entity: Optional[str] = None
    ha_heating_entity: Optional[str] = None
    extra_entities: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    floor: Optional[str] = None
    area_m2: Optional[float] = None
    ha_temperature_entity: Optional[str] = None
    ha_humidity_entity: Optional[str] = None
    ha_occupancy_entity: Optional[str] = None
    ha_heating_entity: Optional[str] = None
    extra_entities: Optional[list[str]] = None
    metadata: Optional[dict] = None


class RoomResponse(BaseModel):
    id: UUID
    room_id: str
    name: str
    floor: Optional[str]
    area_m2: Optional[float]
    ha_temperature_entity: Optional[str]
    ha_humidity_entity: Optional[str]
    ha_occupancy_entity: Optional[str]
    ha_heating_entity: Optional[str]
    extra_entities: list[str]
    metadata: dict
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Simulation
# ─────────────────────────────────────────────────────────────────────────────

class ScenarioID(str, Enum):
    A_BASELINE = "A"
    B_AGGRESSIVE_BATTERY = "B"
    C_EV_PV_ONLY = "C"
    D_PREHEAT = "D"


SCENARIO_LABELS: dict[ScenarioID, str] = {
    ScenarioID.A_BASELINE: "Baseline (current settings)",
    ScenarioID.B_AGGRESSIVE_BATTERY: "Aggressive battery cycling",
    ScenarioID.C_EV_PV_ONLY: "EV charges only from PV",
    ScenarioID.D_PREHEAT: "Pre-heat house during low-demand hours",
}


class SimulationRequest(BaseModel):
    scenarios: list[ScenarioID] = Field(
        default_factory=lambda: list(ScenarioID),
        description="Which scenarios to simulate (defaults to all)",
    )
    pv_forecast_kwh: Optional[list[float]] = Field(
        None,
        description="24 hourly PV production values (kWh). Auto-fetched from HA if omitted.",
    )
    horizon_hours: int = Field(24, ge=1, le=48)
    ev_target_kwh: Optional[float] = Field(
        None,
        description="EV charge target in kWh. Defaults to fill to 80%.",
    )
    ev_departure_hour: int = Field(7, ge=0, le=23)


class HourlyResult(BaseModel):
    hour: int
    pv_kwh: float
    house_kwh: float
    ev_kwh: float
    heating_extra_kwh: float
    battery_delta_kwh: float   # positive = charged
    grid_import_kwh: float
    grid_export_kwh: float
    battery_soc_pct: float


class ScenarioResult(BaseModel):
    scenario_id: ScenarioID
    scenario_name: str
    grid_import_kwh: float
    grid_export_kwh: float
    energy_cost_eur: float
    self_sufficiency_pct: float
    battery_cycles: float
    ev_charged_kwh: float
    comfort_score: float          # 0–100 (higher = more comfortable)
    hourly: list[HourlyResult]


class SimulationReport(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    horizon_hours: int
    scenarios: list[ScenarioResult]
    baseline_id: ScenarioID = ScenarioID.A_BASELINE
    best_cost_id: Optional[ScenarioID] = None
    best_sufficiency_id: Optional[ScenarioID] = None
    savings_vs_baseline_eur: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# API responses
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str = "digital-twin"
    version: str = "1.0.0"
    db_connected: bool = False
    ha_reachable: bool = False
