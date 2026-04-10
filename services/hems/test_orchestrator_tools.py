"""Unit tests for orchestrator tools (#1084 #1085 #1086 #1087 #1088).

Tests:
- get_battery_roi_status: Returns dict with expected keys
- get_oven_recommendation: Returns dict with light_oven as bool
- get_energy_economics: Returns dict with electricity_price_eur_kwh > 0
- orchestrator_client timeout handling: Timeouts are caught and returned as error dicts
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the functions under test
from orchestrator_tools import (
    get_battery_roi_status,
    get_oven_recommendation,
    get_energy_economics,
)
from orchestrator_client import OrchestratorClient


# ============================================================================
# Tests for get_battery_roi_status
# ============================================================================


@pytest.mark.asyncio
async def test_get_battery_roi_status_returns_dict() -> None:
    """Test that get_battery_roi_status returns a dict with expected keys."""
    result = await get_battery_roi_status()

    assert isinstance(result, dict)
    assert "battery_capacity_kwh" in result
    assert "estimated_daily_cycles" in result
    assert "daily_savings_eur" in result
    assert "payback_years" in result
    assert "status" in result

    # Check types
    assert isinstance(result["battery_capacity_kwh"], float)
    assert isinstance(result["estimated_daily_cycles"], float)
    assert isinstance(result["daily_savings_eur"], float)
    assert isinstance(result["payback_years"], float)
    assert isinstance(result["status"], str)


@pytest.mark.asyncio
async def test_get_battery_roi_status_values_reasonable() -> None:
    """Test that ROI status values are within reasonable ranges."""
    result = await get_battery_roi_status()

    # Battery capacity should be positive
    assert result["battery_capacity_kwh"] > 0

    # Cycles should be between 0 and 5
    assert 0 <= result["estimated_daily_cycles"] <= 5

    # Savings should be non-negative
    assert result["daily_savings_eur"] >= 0

    # Payback years should be positive and reasonable (< 30 years)
    assert 0 < result["payback_years"] < 30

    # Status should be one of the expected values
    assert result["status"] in ("tracking", "unavailable")


# ============================================================================
# Tests for get_oven_recommendation
# ============================================================================


@pytest.mark.asyncio
async def test_get_oven_recommendation_returns_bool() -> None:
    """Test that get_oven_recommendation returns dict with light_oven as bool."""
    result = await get_oven_recommendation()

    assert isinstance(result, dict)
    assert "light_oven" in result
    assert "start_time" in result
    assert "reason" in result

    # Check types
    assert isinstance(result["light_oven"], bool)
    assert isinstance(result["reason"], str)
    # start_time can be None or ISO string
    assert result["start_time"] is None or isinstance(result["start_time"], str)


@pytest.mark.asyncio
async def test_get_oven_recommendation_cold_start() -> None:
    """Test oven recommendation with cold start (low current temp)."""
    with patch.dict("os.environ", {"CURRENT_ROOM_TEMP": "10.0"}):
        # Clear the module cache to pick up new env vars
        import importlib
        import orchestrator_tools

        importlib.reload(orchestrator_tools)
        from orchestrator_tools import get_oven_recommendation as get_oven_reloaded

        result = await get_oven_reloaded()

        # Cold start should trigger urgent recommendation
        assert isinstance(result["light_oven"], bool)
        assert "Start" in result["reason"]


# ============================================================================
# Tests for get_energy_economics
# ============================================================================


@pytest.mark.asyncio
async def test_get_energy_economics_has_price() -> None:
    """Test that get_energy_economics returns electricity price > 0."""
    result = await get_energy_economics()

    assert isinstance(result, dict)
    assert "electricity_price_eur_kwh" in result
    assert "gas_price_eur_kwh" in result
    assert "pv_fraction_today" in result
    assert "savings_today_eur" in result
    assert "status" in result

    # Check types
    assert isinstance(result["electricity_price_eur_kwh"], float)
    assert isinstance(result["gas_price_eur_kwh"], float)
    assert isinstance(result["pv_fraction_today"], float)
    assert isinstance(result["savings_today_eur"], float)
    assert isinstance(result["status"], str)


@pytest.mark.asyncio
async def test_get_energy_economics_prices_reasonable() -> None:
    """Test that energy economics prices are within reasonable ranges."""
    result = await get_energy_economics()

    # Electricity price should be between 0.1 and 1.0 EUR/kWh
    assert 0.1 <= result["electricity_price_eur_kwh"] <= 1.0

    # Gas price should be between 0.05 and 0.5 EUR/kWh
    assert 0.05 <= result["gas_price_eur_kwh"] <= 0.5

    # PV fraction should be between 0 and 1
    assert 0 <= result["pv_fraction_today"] <= 1.0

    # Savings should be non-negative
    assert result["savings_today_eur"] >= 0

    # Status should be one of the expected values
    assert result["status"] in ("available", "partial", "unavailable")


# ============================================================================
# Tests for OrchestratorClient timeout handling
# ============================================================================


@pytest.mark.asyncio
async def test_orchestrator_client_timeout_handled() -> None:
    """Test that client timeout is caught and returned as error dict."""
    client = OrchestratorClient()

    # Mock httpx to raise TimeoutException
    with patch("orchestrator_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Raise timeout on post
        import httpx

        mock_client.post.side_effect = httpx.TimeoutException("Request timeout")
        mock_client_class.return_value = mock_client

        # Mock token acquisition
        with patch.object(client, "_get_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            # Mock audit logging to avoid DB errors
            with patch.object(
                client, "_audit_log", new_callable=AsyncMock
            ) as mock_audit:
                result = await client.execute_tool("test_tool", {})

                # Should return error dict, not raise exception
                assert isinstance(result, dict)
                assert "error" in result
                assert result["tool"] == "test_tool"

                # Audit log should have been called
                assert mock_audit.called


@pytest.mark.asyncio
async def test_orchestrator_client_audit_log_best_effort() -> None:
    """Test that audit logging failures don't break tool execution."""
    client = OrchestratorClient()

    # Mock successful tool execution
    with patch("orchestrator_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        response = MagicMock()
        response.json.return_value = {"result": "success"}
        mock_client.post.return_value = response
        mock_client_class.return_value = mock_client

        # Mock token acquisition
        with patch.object(client, "_get_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            # Mock audit logging to raise exception
            with patch.object(
                client, "_audit_log", new_callable=AsyncMock
            ) as mock_audit:
                mock_audit.side_effect = Exception("DB connection failed")

                # Should still return successful result
                result = await client.execute_tool("test_tool", {"param": "value"})

                assert result["result"] == "success"
                # Audit log was attempted but failure was swallowed
                assert mock_audit.called


@pytest.mark.asyncio
async def test_orchestrator_client_execute_tool_timeout_constant() -> None:
    """Test that execute_tool uses the correct timeout value."""
    from orchestrator_client import TOOL_EXECUTE_TIMEOUT_SECONDS

    # Timeout should be 30 seconds
    assert TOOL_EXECUTE_TIMEOUT_SECONDS == 30.0


@pytest.mark.asyncio
async def test_orchestrator_client_success_path() -> None:
    """Test successful tool execution with audit logging."""
    client = OrchestratorClient()

    # Mock successful execution
    with patch("orchestrator_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        response = MagicMock()
        response.json.return_value = {
            "battery_capacity_kwh": 7.0,
            "status": "available",
        }
        mock_client.post.return_value = response
        mock_client_class.return_value = mock_client

        with patch.object(client, "_get_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            with patch.object(
                client, "_audit_log", new_callable=AsyncMock
            ) as mock_audit:
                result = await client.execute_tool("get_battery_roi_status", {})

                assert result["battery_capacity_kwh"] == 7.0
                assert mock_audit.called

                # Check audit log arguments
                call_args = mock_audit.call_args
                assert call_args[0][0] == "get_battery_roi_status"  # tool_name
                assert call_args[0][1] == {}  # params
                assert "battery_capacity_kwh" in call_args[0][2]  # result
                assert isinstance(call_args[0][3], float)  # duration_ms


# ============================================================================
# Integration-like tests
# ============================================================================


@pytest.mark.asyncio
async def test_all_tools_return_dicts() -> None:
    """Smoke test: all orchestrator tools return dicts."""
    battery = await get_battery_roi_status()
    oven = await get_oven_recommendation()
    economics = await get_energy_economics()

    assert isinstance(battery, dict)
    assert isinstance(oven, dict)
    assert isinstance(economics, dict)


@pytest.mark.asyncio
async def test_all_tools_include_status() -> None:
    """Test that all tools include a status field."""
    battery = await get_battery_roi_status()
    economics = await get_energy_economics()

    assert "status" in battery
    assert "status" in economics


@pytest.mark.asyncio
async def test_oven_recommendation_fields_complete() -> None:
    """Test that oven recommendation includes all necessary fields."""
    result = await get_oven_recommendation()

    required_fields = ["light_oven", "start_time", "reason"]
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
