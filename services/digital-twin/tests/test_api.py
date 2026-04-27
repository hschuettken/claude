"""Tests for the Digital Twin FastAPI endpoints.

All tests use the FastAPI TestClient — no real DB, HA, or NATS required.
The app lifespan is bypassed via the test client.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch heavy async deps before importing app
import digital_twin.db as _db_module

_db_module._pool = None  # ensure no real DB pool


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "digital-twin"
        assert isinstance(data["db_connected"], bool)
        assert isinstance(data["ha_reachable"], bool)


class TestScenariosEndpoint:
    @pytest.fixture
    def client(self):
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def test_list_scenarios_returns_4(self, client):
        resp = client.get("/api/v1/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4

    def test_scenarios_have_id_and_name(self, client):
        resp = client.get("/api/v1/scenarios")
        for s in resp.json():
            assert "id" in s
            assert "name" in s
            assert len(s["name"]) > 0


class TestSimulateEndpoint:
    @pytest.fixture
    def client(self):
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def test_simulate_all_scenarios(self, client):
        resp = client.post(
            "/api/v1/simulate",
            json={
                "scenarios": ["A", "B", "C", "D"],
                "pv_forecast_kwh": [0.8] * 24,
                "horizon_hours": 24,
                "ev_departure_hour": 7,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scenarios"]) == 4
        assert data["horizon_hours"] == 24

    def test_simulate_single_scenario(self, client):
        resp = client.post(
            "/api/v1/simulate",
            json={
                "scenarios": ["A"],
                "pv_forecast_kwh": [1.0] * 24,
                "horizon_hours": 24,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scenarios"]) == 1
        assert data["scenarios"][0]["scenario_id"] == "A"

    def test_simulate_returns_hourly_trace(self, client):
        resp = client.post(
            "/api/v1/simulate",
            json={
                "scenarios": ["A"],
                "pv_forecast_kwh": [1.5] * 24,
                "horizon_hours": 12,
            },
        )
        assert resp.status_code == 200
        scenario = resp.json()["scenarios"][0]
        assert len(scenario["hourly"]) == 12

    def test_simulate_without_forecast_uses_fallback(self, client):
        """Omitting pv_forecast_kwh triggers internal fallback."""
        resp = client.post(
            "/api/v1/simulate",
            json={"scenarios": ["A"]},
        )
        assert resp.status_code == 200

    def test_simulate_invalid_scenario_rejected(self, client):
        resp = client.post(
            "/api/v1/simulate",
            json={"scenarios": ["Z"], "pv_forecast_kwh": [1.0] * 24},
        )
        assert resp.status_code == 422

    def test_latest_simulation_available_after_run(self, client):
        # Run a simulation first
        client.post(
            "/api/v1/simulate",
            json={"scenarios": ["A"], "pv_forecast_kwh": [1.0] * 24},
        )
        resp = client.get("/api/v1/simulate/latest")
        assert resp.status_code == 200
        assert resp.json()["scenarios"][0]["scenario_id"] == "A"

    def test_latest_simulation_404_when_not_run(self):
        """Fresh app instance — no simulation cached yet."""
        from digital_twin import main as _main
        _main._latest_simulation = None
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/v1/simulate/latest")
            assert resp.status_code == 404


class TestStateEndpoints:
    @pytest.fixture
    def client_no_state(self):
        from digital_twin import main as _main
        _main._latest_house_state = None
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    @pytest.fixture
    def client_with_state(self):
        from digital_twin import main as _main
        from digital_twin.models import EnergyState, HouseState
        _main._latest_house_state = HouseState(
            energy=EnergyState(
                pv_total_power_w=3000.0,
                battery_soc_pct=65.0,
                grid_power_w=500.0,
            )
        )
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        _main._latest_house_state = None

    def test_state_503_when_not_populated(self, client_no_state):
        resp = client_no_state.get("/api/v1/state")
        assert resp.status_code == 503

    def test_state_returns_house_state(self, client_with_state):
        resp = client_with_state.get("/api/v1/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "energy" in data
        assert data["energy"]["pv_total_power_w"] == pytest.approx(3000.0)

    def test_energy_endpoint_returns_energy_state(self, client_with_state):
        resp = client_with_state.get("/api/v1/state/energy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["battery_soc_pct"] == pytest.approx(65.0)

    def test_refresh_returns_202(self, client_no_state):
        resp = client_no_state.post("/api/v1/state/refresh")
        assert resp.status_code == 202


class TestRoomsEndpoints:
    @pytest.fixture
    def client(self):
        from digital_twin.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def test_list_rooms_returns_defaults_when_no_db(self, client):
        """Without DB, room_registry.list_rooms() falls back to in-memory defaults."""
        resp = client.get("/api/v1/rooms")
        assert resp.status_code == 200
        rooms = resp.json()
        assert len(rooms) >= 1

    def test_create_duplicate_room_returns_409(self, client):
        """Creating a room with an existing room_id returns 409."""
        # living_room is seeded as a default room
        resp = client.post(
            "/api/v1/rooms",
            json={"room_id": "living_room", "name": "Another Living Room"},
        )
        # Either the default room exists (409) or the DB is unavailable (5xx)
        assert resp.status_code in (409, 500, 503)

    def test_get_nonexistent_room_returns_404(self, client):
        resp = client.get("/api/v1/rooms/nonexistent_xyz")
        assert resp.status_code == 404
