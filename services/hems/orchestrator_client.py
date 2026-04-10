"""HEMS Orchestrator client with Bifrost JWT auth (#1049).

Wraps the Orchestrator tool-execute endpoint. Handles JWT token acquisition
via Bifrost and caches it for 23 hours to avoid per-request auth overhead.

Includes audit logging (#1087) for all tool executions to hems.decisions table.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

import asyncpg
import httpx

logger = logging.getLogger("hems.orchestrator_client")

BIFROST_URL = "http://192.168.0.50:8400"
ORCHESTRATOR_URL = "http://192.168.0.50:8050"
TOKEN_TTL_SECONDS = 23 * 3600  # 23 hours
TOOL_EXECUTE_TIMEOUT_SECONDS = 30.0
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)


class OrchestratorClient:
    """Client for the HEMS → Orchestrator integration via Bifrost JWT auth."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("BIFROST_HEMS_API_KEY", "hems_api_key_dev")
        self._jwt: Optional[str] = None
        self._jwt_acquired_at: float = 0.0

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _token_is_valid(self) -> bool:
        if self._jwt is None:
            return False
        age = time.monotonic() - self._jwt_acquired_at
        return age < TOKEN_TTL_SECONDS

    async def _acquire_token(self) -> str:
        """POST to Bifrost /auth/token and cache the returned JWT."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{BIFROST_URL}/auth/token",
                json={"agent_name": "hems", "api_key": self._api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        token: str = data["access_token"]
        self._jwt = token
        self._jwt_acquired_at = time.monotonic()
        logger.debug("Acquired new Bifrost JWT for hems agent")
        return token

    async def _get_token(self) -> str:
        """Return cached JWT or acquire a fresh one."""
        if not self._token_is_valid():
            return await self._acquire_token()
        return self._jwt  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _audit_log(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float,
    ) -> None:
        """Log orchestrator tool execution to hems.decisions table.

        Args:
            tool_name: Name of the tool executed.
            params: Parameters passed to the tool.
            result: Result dict returned by the tool.
            duration_ms: Execution time in milliseconds.

        Best-effort logging — failures are logged but never raised.
        """
        try:
            pg_url = DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql://"
            ).replace("postgresql+psycopg2://", "postgresql://")
            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    """
                    INSERT INTO hems.decisions
                        (mode, flow_temp_setpoint, reason, pv_available_w, outdoor_temp_c)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    "orchestrator",  # mode
                    duration_ms / 1000.0,  # flow_temp_setpoint (repurposed)
                    f"orchestrator_tool: {tool_name}",  # reason
                    float(params.get("param_count", 0)),  # pv_available_w (repurposed)
                    float(
                        1 if result.get("status") == "available" else 0
                    ),  # outdoor_temp_c (repurposed)
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Failed to log orchestrator tool execution: %s", e)

    # ------------------------------------------------------------------
    # Core execute
    # ------------------------------------------------------------------

    async def execute_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a named tool on the Orchestrator with timing and audit logging.

        Args:
            tool_name: Orchestrator tool identifier.
            params: Tool parameter dict.

        Returns:
            Result dict from the Orchestrator response.

        Enforces 30-second timeout and logs execution to audit trail.
        """
        start_time = time.monotonic()
        result = {}

        try:
            token = await self._get_token()

            async with httpx.AsyncClient(
                timeout=TOOL_EXECUTE_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(
                    f"{ORCHESTRATOR_URL}/api/v1/tools/execute",
                    json={"tool": tool_name, "params": params},
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                result = resp.json()

        except asyncio.TimeoutError:
            logger.error("Tool execution timeout for %s", tool_name)
            result = {"error": "timeout", "tool": tool_name}
        except httpx.TimeoutException:
            logger.error("HTTP timeout for tool %s", tool_name)
            result = {"error": "http_timeout", "tool": tool_name}
        except Exception as e:
            logger.error("Tool execution failed for %s: %s", tool_name, e)
            result = {"error": str(e), "tool": tool_name}

        finally:
            # Always audit log, even on failure (best-effort)
            duration_ms = (time.monotonic() - start_time) * 1000
            try:
                await self._audit_log(tool_name, params, result, duration_ms)
            except Exception as audit_error:
                # Best-effort: never raise from finally
                logger.warning("Audit log failed for %s: %s", tool_name, audit_error)

        return result

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def get_battery_roi_status(self) -> dict[str, Any]:
        """Fetch battery ROI status from the Orchestrator."""
        return await self.execute_tool("get_battery_roi_status", {})

    async def get_energy_economics(self) -> dict[str, Any]:
        """Fetch current energy economics from the Orchestrator."""
        return await self.execute_tool("get_energy_economics", {})
