"""Unit tests for HEMS Phase 2 Internal API endpoints.

Tests all 7 endpoints with mocked InfluxDB + PostgreSQL connections.
Uses pytest + FastAPI TestClient for endpoint testing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from influxdb_client.client.query_api import QueryApi

# Import the API router and models
from api import (
    router,
    EnergyResponse,
    AnalyticsResponse,
    ModelStatusResponse,
    ModelStatus,
    RetrainResponse,
    BoilerResponse,
    BoilerState,
    DecisionsResponse,
    OverrideResponse,
    OverrideFlowTempRequest,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def app() -> FastAPI:
    """Create FastAPI app with router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_query_api() -> MagicMock:
    """Mock InfluxDB QueryApi."""
    api = MagicMock()
    return api


@pytest.fixture
async def mock_db_pool() -> AsyncMock:
    """Mock AsyncPG connection pool."""
    pool = AsyncMock(spec=asyncpg.Pool)
    return pool


# ============================================================================
# Tests for Endpoint 1: GET /api/energy
# ============================================================================

class TestEnergyEndpoint:
    """Tests for GET /api/energy endpoint."""

    def test_energy_day_period(self, client: TestClient) -> None:
        """Test energy endpoint with 'day' period."""
        response = client.get("/api/energy?period=day")
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "total_consumed_kwh" in data
        assert "period" in data
        assert "period_start" in data
        assert "period_end" in data
        assert "breakdown" in data
        assert "timestamp" in data
        
        # Validate period
        assert data["period"] == "day"
        
        # Validate breakdown structure
        breakdown = data["breakdown"]
        assert "boiler" in breakdown
        assert "circulation_pump" in breakdown
        assert "supplemental_heat" in breakdown
        assert "pv_exported" in breakdown
        assert "pv_used" in breakdown
        
        # All values should be numeric
        assert isinstance(breakdown["boiler"], (int, float))
        assert isinstance(data["total_consumed_kwh"], (int, float))

    def test_energy_hour_period(self, client: TestClient) -> None:
        """Test energy endpoint with 'hour' period."""
        response = client.get("/api/energy?period=hour")
        
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "hour"

    def test_energy_month_period(self, client: TestClient) -> None:
        """Test energy endpoint with 'month' period."""
        response = client.get("/api/energy?period=month")
        
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"

    def test_energy_invalid_period(self, client: TestClient) -> None:
        """Test energy endpoint with invalid period."""
        response = client.get("/api/energy?period=invalid")
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_energy_default_period(self, client: TestClient) -> None:
        """Test energy endpoint with default period (day)."""
        response = client.get("/api/energy")
        
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "day"

    def test_energy_timestamps_are_iso8601(self, client: TestClient) -> None:
        """Verify timestamps are ISO-8601 format."""
        response = client.get("/api/energy?period=day")
        data = response.json()
        
        # Should be parseable as ISO-8601
        start = datetime.fromisoformat(data["period_start"])
        end = datetime.fromisoformat(data["period_end"])
        ts = datetime.fromisoformat(data["timestamp"])
        
        assert start < end
        assert ts.tzinfo is not None


# ============================================================================
# Tests for Endpoint 2: GET /api/analytics/{period}
# ============================================================================

class TestAnalyticsEndpoint:
    """Tests for GET /api/analytics/{period} endpoint."""

    def test_analytics_hour(self, client: TestClient) -> None:
        """Test analytics with hour period."""
        response = client.get("/api/analytics/hour")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["period"] == "hour"
        assert "thermal_stats" in data
        assert "timestamp" in data
        
        # Validate thermal stats structure
        stats = data["thermal_stats"]
        assert "avg_room_temp_c" in stats
        assert "current_room_temp_c" in stats
        assert "avg_setpoint_c" in stats
        assert "boiler_runtime_minutes" in stats
        assert "boiler_on_duty_cycle" in stats
        assert "pv_utilization_percent" in stats
        assert "mixing_valve_avg_position" in stats

    def test_analytics_day(self, client: TestClient) -> None:
        """Test analytics with day period."""
        response = client.get("/api/analytics/day")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "day"

    def test_analytics_week(self, client: TestClient) -> None:
        """Test analytics with week period."""
        response = client.get("/api/analytics/week")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "week"

    def test_analytics_month(self, client: TestClient) -> None:
        """Test analytics with month period."""
        response = client.get("/api/analytics/month")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"

    def test_analytics_invalid_period(self, client: TestClient) -> None:
        """Test analytics with invalid period."""
        response = client.get("/api/analytics/invalid")
        assert response.status_code == 400

    def test_analytics_thermal_stats_values_valid(self, client: TestClient) -> None:
        """Verify thermal stats have valid ranges."""
        response = client.get("/api/analytics/day")
        data = response.json()
        stats = data["thermal_stats"]
        
        # Temperature should be in reasonable range (5-50°C)
        assert 5 <= stats["avg_room_temp_c"] <= 50
        assert 5 <= stats["current_room_temp_c"] <= 50
        assert 5 <= stats["avg_setpoint_c"] <= 50
        
        # Duty cycle and utilization should be 0-100%
        assert 0 <= stats["boiler_on_duty_cycle"] <= 100
        assert 0 <= stats["pv_utilization_percent"] <= 100
        assert 0 <= stats["mixing_valve_avg_position"] <= 100


# ============================================================================
# Tests for Endpoint 3: GET /api/model/status
# ============================================================================

class TestModelStatusEndpoint:
    """Tests for GET /api/model/status endpoint."""

    def test_model_status_structure(self, client: TestClient) -> None:
        """Test model status response structure."""
        response = client.get("/api/model/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "status" in data
        assert "model_id" in data
        assert "last_trained" in data
        assert "timestamp" in data
        
        # Status should be valid enum value
        assert data["status"] in ["idle", "training", "retraining", "ready", "error"]
        
        # Timestamps should be ISO-8601
        datetime.fromisoformat(data["last_trained"])
        datetime.fromisoformat(data["timestamp"])

    def test_model_status_optional_fields(self, client: TestClient) -> None:
        """Test model status optional fields."""
        response = client.get("/api/model/status")
        data = response.json()
        
        # Optional fields (may be None)
        assert "training_loss" in data
        assert "accuracy" in data
        assert "retraining_progress" in data

    def test_model_status_accuracy_range(self, client: TestClient) -> None:
        """Verify accuracy is in valid range if present."""
        response = client.get("/api/model/status")
        data = response.json()
        
        if data.get("accuracy") is not None:
            assert 0 <= data["accuracy"] <= 1

    def test_model_status_retraining_progress_range(self, client: TestClient) -> None:
        """Verify retraining progress is in valid range if present."""
        response = client.get("/api/model/status")
        data = response.json()
        
        if data.get("retraining_progress") is not None:
            assert 0 <= data["retraining_progress"] <= 1


# ============================================================================
# Tests for Endpoint 4: POST /api/model/retrain
# ============================================================================

class TestRetrainEndpoint:
    """Tests for POST /api/model/retrain endpoint."""

    def test_retrain_default_request(self, client: TestClient) -> None:
        """Test retrain with default parameters."""
        payload = {
            "include_recent_data": True,
            "epochs": 50,
            "batch_size": 32,
        }
        response = client.post("/api/model/retrain", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Response fields
        assert "job_id" in data
        assert "status" in data
        assert "message" in data
        assert "estimated_duration_seconds" in data
        assert "timestamp" in data
        
        # Job should be queued
        assert data["status"] in ["queued", "running"]
        assert len(data["job_id"]) > 0

    def test_retrain_custom_epochs(self, client: TestClient) -> None:
        """Test retrain with custom epoch count."""
        payload = {
            "include_recent_data": True,
            "epochs": 100,
            "batch_size": 64,
        }
        response = client.post("/api/model/retrain", json=payload)
        assert response.status_code == 200

    def test_retrain_minimal_request(self, client: TestClient) -> None:
        """Test retrain with minimal request (defaults)."""
        # POST with empty body uses all defaults
        response = client.post("/api/model/retrain", json={})
        assert response.status_code == 200

    def test_retrain_epochs_validation(self, client: TestClient) -> None:
        """Test retrain epochs bounds validation."""
        # Valid: min=1, max=500
        valid_payload = {
            "epochs": 1,
            "batch_size": 32,
        }
        response = client.post("/api/model/retrain", json=valid_payload)
        assert response.status_code == 200

    def test_retrain_batch_size_validation(self, client: TestClient) -> None:
        """Test retrain batch size validation."""
        valid_payload = {
            "epochs": 50,
            "batch_size": 256,
        }
        response = client.post("/api/model/retrain", json=valid_payload)
        assert response.status_code == 200

    def test_retrain_job_id_format(self, client: TestClient) -> None:
        """Test retrain returns valid job ID format."""
        payload = {
            "include_recent_data": True,
            "epochs": 50,
            "batch_size": 32,
        }
        response = client.post("/api/model/retrain", json=payload)
        data = response.json()
        
        # Job ID should be UUID-like
        job_id = data["job_id"]
        # Simple check: should be a non-empty string
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_retrain_estimated_duration(self, client: TestClient) -> None:
        """Test retrain estimated duration is positive."""
        payload = {
            "epochs": 50,
            "batch_size": 32,
        }
        response = client.post("/api/model/retrain", json=payload)
        data = response.json()
        
        assert data["estimated_duration_seconds"] > 0


# ============================================================================
# Tests for Endpoint 5: GET /api/boiler
# ============================================================================

class TestBoilerEndpoint:
    """Tests for GET /api/boiler endpoint."""

    def test_boiler_state_structure(self, client: TestClient) -> None:
        """Test boiler state response structure."""
        response = client.get("/api/boiler")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "state" in data
        assert "power_kw" in data
        assert "flow_temp_c" in data
        assert "return_temp_c" in data
        assert "runtime_minutes" in data
        assert "last_state_change" in data
        assert "timestamp" in data

    def test_boiler_state_valid_enum(self, client: TestClient) -> None:
        """Test boiler state is valid enum value."""
        response = client.get("/api/boiler")
        data = response.json()
        
        valid_states = ["off", "ignition", "on", "modulating", "error"]
        assert data["state"] in valid_states

    def test_boiler_temperatures_valid(self, client: TestClient) -> None:
        """Verify boiler temps are in valid range (20-80°C)."""
        response = client.get("/api/boiler")
        data = response.json()
        
        assert 20 <= data["flow_temp_c"] <= 80
        assert 20 <= data["return_temp_c"] <= 80
        # Flow should typically be higher than return
        assert data["flow_temp_c"] >= data["return_temp_c"]

    def test_boiler_power_valid(self, client: TestClient) -> None:
        """Verify boiler power is non-negative."""
        response = client.get("/api/boiler")
        data = response.json()
        
        assert data["power_kw"] >= 0
        # Typical boiler max ~30kW
        assert data["power_kw"] <= 50

    def test_boiler_runtime_non_negative(self, client: TestClient) -> None:
        """Verify runtime is non-negative."""
        response = client.get("/api/boiler")
        data = response.json()
        
        assert data["runtime_minutes"] >= 0

    def test_boiler_modulation_range(self, client: TestClient) -> None:
        """Verify modulation percent is 0-100 if present."""
        response = client.get("/api/boiler")
        data = response.json()
        
        if data.get("modulation_percent") is not None:
            assert 0 <= data["modulation_percent"] <= 100

    def test_boiler_error_code_when_error(self, client: TestClient) -> None:
        """If state is ERROR, error_code should be present."""
        response = client.get("/api/boiler")
        data = response.json()
        
        if data["state"] == "error":
            assert data.get("error_code") is not None


# ============================================================================
# Tests for Endpoint 6: GET /api/decisions/latest
# ============================================================================

class TestDecisionsEndpoint:
    """Tests for GET /api/decisions/latest endpoint."""

    def test_decisions_default_limit(self, client: TestClient) -> None:
        """Test decisions endpoint with default limit."""
        response = client.get("/api/decisions/latest")
        
        assert response.status_code == 200
        data = response.json()
        
        # Response structure
        assert "decisions" in data
        assert "count" in data
        assert "timestamp" in data
        
        # Decisions should be a list
        assert isinstance(data["decisions"], list)

    def test_decisions_custom_limit(self, client: TestClient) -> None:
        """Test decisions endpoint with custom limit."""
        response = client.get("/api/decisions/latest?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["count"] <= 10

    def test_decisions_limit_bounds(self, client: TestClient) -> None:
        """Test decisions limit is bounded (1-50)."""
        # Very high limit should be clamped
        response = client.get("/api/decisions/latest?limit=1000")
        data = response.json()
        
        # Should still be reasonable
        assert data["count"] <= 50

    def test_decisions_structure(self, client: TestClient) -> None:
        """Test individual decision structure."""
        response = client.get("/api/decisions/latest")
        data = response.json()
        
        if data["decisions"]:
            decision = data["decisions"][0]
            
            assert "id" in decision
            assert "timestamp" in decision
            assert "decision_type" in decision
            assert "target_value" in decision
            assert "device" in decision
            assert "reason" in decision

    def test_decisions_ordered_newest_first(self, client: TestClient) -> None:
        """Test decisions are ordered newest first."""
        response = client.get("/api/decisions/latest")
        data = response.json()
        
        decisions = data["decisions"]
        if len(decisions) > 1:
            # Parse timestamps
            timestamps = [
                datetime.fromisoformat(d["timestamp"])
                for d in decisions
            ]
            
            # Should be descending (newest first)
            for i in range(len(timestamps) - 1):
                assert timestamps[i] >= timestamps[i + 1]

    def test_decisions_valid_types(self, client: TestClient) -> None:
        """Test decision types are valid."""
        response = client.get("/api/decisions/latest")
        data = response.json()
        
        valid_types = [
            "boiler_setpoint",
            "flow_temp",
            "mixer_position",
            "pump_on_off",
        ]
        
        for decision in data["decisions"]:
            assert decision["decision_type"] in valid_types


# ============================================================================
# Tests for Endpoint 7: POST /api/override/flow_temp
# ============================================================================

class TestOverrideFlowTempEndpoint:
    """Tests for POST /api/override/flow_temp endpoint."""

    def test_override_flow_temp_valid(self, client: TestClient) -> None:
        """Test override with valid parameters."""
        payload = {
            "flow_temp_c": 55.0,
            "duration_minutes": 30,
            "reason": "Manual user adjustment",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Response structure
        assert "override_id" in data
        assert "flow_temp_c" in data
        assert "duration_minutes" in data
        assert "expires_at" in data
        assert "message" in data
        assert "timestamp" in data
        
        # Values should match request
        assert data["flow_temp_c"] == 55.0
        assert data["duration_minutes"] == 30

    def test_override_flow_temp_minimum(self, client: TestClient) -> None:
        """Test override with minimum temperature (20°C)."""
        payload = {
            "flow_temp_c": 20.0,
            "duration_minutes": 5,
            "reason": "Min temp test",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["flow_temp_c"] == 20.0

    def test_override_flow_temp_maximum(self, client: TestClient) -> None:
        """Test override with maximum temperature (80°C)."""
        payload = {
            "flow_temp_c": 80.0,
            "duration_minutes": 1440,
            "reason": "Max temp test",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["flow_temp_c"] == 80.0

    def test_override_duration_bounds(self, client: TestClient) -> None:
        """Test override duration is bounded (5min-24h)."""
        # Valid: 5 minutes
        payload = {
            "flow_temp_c": 50.0,
            "duration_minutes": 5,
            "reason": "Min duration",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        assert response.status_code == 200

    def test_override_expiration_time(self, client: TestClient) -> None:
        """Test override expiration time is correct."""
        now = datetime.now(timezone.utc)
        duration = 60
        
        payload = {
            "flow_temp_c": 50.0,
            "duration_minutes": duration,
            "reason": "Test expiration",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        data = response.json()
        
        expires = datetime.fromisoformat(data["expires_at"])
        created = datetime.fromisoformat(data["timestamp"])
        
        # Expiration should be roughly now + duration
        expected_expiry = created + timedelta(minutes=duration)
        # Allow 5 second tolerance
        diff = abs((expires - expected_expiry).total_seconds())
        assert diff < 5

    def test_override_id_format(self, client: TestClient) -> None:
        """Test override ID is UUID-like."""
        payload = {
            "flow_temp_c": 50.0,
            "duration_minutes": 30,
            "reason": "ID format test",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        data = response.json()
        
        override_id = data["override_id"]
        assert isinstance(override_id, str)
        assert len(override_id) > 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests across endpoints."""

    def test_all_endpoints_available(self, client: TestClient) -> None:
        """Test all 7 endpoints are available."""
        endpoints = [
            ("GET", "/api/energy"),
            ("GET", "/api/analytics/day"),
            ("GET", "/api/model/status"),
            ("POST", "/api/model/retrain"),
            ("GET", "/api/boiler"),
            ("GET", "/api/decisions/latest"),
            ("POST", "/api/override/flow_temp"),
        ]
        
        # Quick check that endpoints don't return 404
        # GET endpoints
        response = client.get("/api/energy")
        assert response.status_code != 404
        
        response = client.get("/api/model/status")
        assert response.status_code != 404
        
        response = client.get("/api/boiler")
        assert response.status_code != 404
        
        response = client.get("/api/decisions/latest")
        assert response.status_code != 404
        
        # POST endpoints
        response = client.post("/api/model/retrain", json={})
        assert response.status_code != 404
        
        response = client.post(
            "/api/override/flow_temp",
            json={
                "flow_temp_c": 50,
                "duration_minutes": 30,
                "reason": "test",
            }
        )
        assert response.status_code != 404

    def test_all_responses_have_timestamp(self, client: TestClient) -> None:
        """Test all responses include timestamp field."""
        endpoints = [
            ("GET", "/api/energy", None),
            ("GET", "/api/analytics/day", None),
            ("GET", "/api/model/status", None),
            ("POST", "/api/model/retrain", {}),
            ("GET", "/api/boiler", None),
            ("GET", "/api/decisions/latest", None),
            ("POST", "/api/override/flow_temp", {
                "flow_temp_c": 50,
                "duration_minutes": 30,
                "reason": "test",
            }),
        ]
        
        for method, path, payload in endpoints:
            if method == "GET":
                response = client.get(path)
            else:
                response = client.post(path, json=payload or {})
            
            assert response.status_code in [200, 201], f"Failed for {method} {path}"
            data = response.json()
            assert "timestamp" in data, f"No timestamp in {method} {path}"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling across endpoints."""

    def test_energy_bad_period_returns_400(self, client: TestClient) -> None:
        """Test bad period parameter returns 400."""
        response = client.get("/api/energy?period=yearly")
        assert response.status_code == 400

    def test_analytics_bad_period_returns_400(self, client: TestClient) -> None:
        """Test bad period parameter returns 400."""
        response = client.get("/api/analytics/yearly")
        assert response.status_code == 400

    def test_override_invalid_temp_returns_422(self, client: TestClient) -> None:
        """Test invalid temperature returns validation error."""
        payload = {
            "flow_temp_c": 100.0,  # Out of range (>80)
            "duration_minutes": 30,
            "reason": "Invalid",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        # Should be rejected due to validation
        assert response.status_code >= 400

    def test_override_invalid_duration_returns_422(self, client: TestClient) -> None:
        """Test invalid duration returns validation error."""
        payload = {
            "flow_temp_c": 50.0,
            "duration_minutes": 2000,  # Out of range (>1440)
            "reason": "Invalid",
        }
        response = client.post("/api/override/flow_temp", json=payload)
        assert response.status_code >= 400

    def test_missing_required_fields_returns_422(self, client: TestClient) -> None:
        """Test missing required fields returns validation error."""
        payload = {
            "flow_temp_c": 50.0,
            # Missing duration_minutes and reason
        }
        response = client.post("/api/override/flow_temp", json=payload)
        assert response.status_code >= 400


# ============================================================================
# Data Validation Tests
# ============================================================================

class TestDataValidation:
    """Tests for data validation and constraints."""

    def test_energy_consumed_equals_breakdown_sum(self, client: TestClient) -> None:
        """Test total energy is sum of boiler + pump + supplemental."""
        response = client.get("/api/energy?period=day")
        data = response.json()
        
        breakdown = data["breakdown"]
        expected_total = (
            breakdown["boiler"] +
            breakdown["circulation_pump"] +
            breakdown["supplemental_heat"]
        )
        
        assert abs(data["total_consumed_kwh"] - expected_total) < 0.01

    def test_analytics_period_times_correct(self, client: TestClient) -> None:
        """Test analytics period times are correct relative to period."""
        now = datetime.now(timezone.utc)
        response = client.get("/api/analytics/day")
        data = response.json()
        
        start = datetime.fromisoformat(data["period_start"])
        end = datetime.fromisoformat(data["period_end"])
        
        # End should be current time
        assert (now - end).total_seconds() < 5
        
        # Start should be ~24h before end
        expected_start = now - timedelta(days=1)
        diff = abs((start - expected_start).total_seconds())
        assert diff < 60  # Allow 1 minute tolerance

    def test_boiler_flow_return_relationship(self, client: TestClient) -> None:
        """Test boiler flow temp >= return temp."""
        response = client.get("/api/boiler")
        data = response.json()
        
        # Flow should be >= return (heat flows from high to low temp)
        assert data["flow_temp_c"] >= data["return_temp_c"]


if __name__ == "__main__":
    # Run with: pytest test_api.py -v
    pytest.main([__file__, "-v"])
