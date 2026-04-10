"""HEMS Orchestrator client with Bifrost JWT auth (#1049).

Wraps the Orchestrator tool-execute endpoint. Handles JWT token acquisition
via Bifrost and caches it for 23 hours to avoid per-request auth overhead.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("hems.orchestrator_client")

BIFROST_URL = "http://192.168.0.50:8400"
ORCHESTRATOR_URL = "http://192.168.0.50:8050"
TOKEN_TTL_SECONDS = 23 * 3600  # 23 hours


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
    # Core execute
    # ------------------------------------------------------------------

    async def execute_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a named tool on the Orchestrator.

        Args:
            tool_name: Orchestrator tool identifier.
            params: Tool parameter dict.

        Returns:
            Result dict from the Orchestrator response.
        """
        token = await self._get_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/api/v1/tools/execute",
                json={"tool": tool_name, "params": params},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def get_battery_roi_status(self) -> dict[str, Any]:
        """Fetch battery ROI status from the Orchestrator."""
        return await self.execute_tool("get_battery_roi_status", {})

    async def get_energy_economics(self) -> dict[str, Any]:
        """Fetch current energy economics from the Orchestrator."""
        return await self.execute_tool("get_energy_economics", {})
