"""Tests for digital-twin Pydantic models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from digital_twin.models import (
    EnergyState,
    HouseState,
    RoomCreate,
    RoomState,
    RoomUpdate,
    ScenarioID,
    SimulationRequest,
    SCENARIO_LABELS,
)


class TestEnergyState:
    def test_defaults(self):
        e = EnergyState()
        assert e.pv_total_power_w == 0.0
        assert e.battery_soc_pct == 0.0
        assert e.ev_soc_pct is None

    def test_pv_total_kw(self):
        e = EnergyState(pv_east_power_w=2000.0, pv_west_power_w=1500.0, pv_total_power_w=3500.0)
        assert e.pv_total_kw == pytest.approx(3.5)

    def test_grid_importing(self):
        e = EnergyState(grid_power_w=-500.0)
        assert e.grid_importing is True

    def test_grid_exporting(self):
        e = EnergyState(grid_power_w=300.0)
        assert e.grid_importing is False

    def test_timestamp_utc(self):
        e = EnergyState()
        assert e.timestamp.tzinfo is not None


class TestHouseState:
    def test_default_rooms_empty(self):
        h = HouseState()
        assert h.rooms == {}

    def test_with_rooms(self):
        room = RoomState(room_id="living_room", name="Living Room", temperature_c=21.5)
        h = HouseState(rooms={"living_room": room})
        assert h.rooms["living_room"].temperature_c == 21.5

    def test_safe_mode_default_off(self):
        h = HouseState()
        assert h.safe_mode is False


class TestRoomCreate:
    def test_valid(self):
        r = RoomCreate(room_id="office", name="Home Office")
        assert r.room_id == "office"
        assert r.extra_entities == []
        assert r.metadata == {}

    def test_room_id_too_short(self):
        with pytest.raises(Exception):
            RoomCreate(room_id="", name="Office")

    def test_full_room(self):
        r = RoomCreate(
            room_id="kitchen",
            name="Kitchen",
            floor="ground",
            area_m2=18.5,
            ha_temperature_entity="sensor.temp_kitchen",
            ha_humidity_entity="sensor.humidity_kitchen",
            extra_entities=["sensor.co2_kitchen"],
            metadata={"has_dishwasher": True},
        )
        assert r.floor == "ground"
        assert r.area_m2 == 18.5
        assert "sensor.co2_kitchen" in r.extra_entities


class TestRoomUpdate:
    def test_partial_update(self):
        u = RoomUpdate(name="Updated Kitchen")
        d = u.model_dump(exclude_none=True)
        assert "name" in d
        assert "floor" not in d


class TestScenarios:
    def test_all_scenarios_have_labels(self):
        for s in ScenarioID:
            assert s in SCENARIO_LABELS
            assert len(SCENARIO_LABELS[s]) > 5

    def test_scenario_ids(self):
        ids = [s.value for s in ScenarioID]
        assert "A" in ids
        assert "B" in ids
        assert "C" in ids
        assert "D" in ids


class TestSimulationRequest:
    def test_default_includes_all_scenarios(self):
        r = SimulationRequest()
        assert len(r.scenarios) == len(list(ScenarioID))

    def test_custom_scenarios(self):
        r = SimulationRequest(scenarios=[ScenarioID.A_BASELINE, ScenarioID.C_EV_PV_ONLY])
        assert len(r.scenarios) == 2

    def test_horizon_defaults(self):
        r = SimulationRequest()
        assert r.horizon_hours == 24
        assert r.ev_departure_hour == 7

    def test_horizon_bounds(self):
        with pytest.raises(Exception):
            SimulationRequest(horizon_hours=0)
        with pytest.raises(Exception):
            SimulationRequest(horizon_hours=100)
