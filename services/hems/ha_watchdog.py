"""Home Assistant watchdog automation for HEMS heartbeat monitoring.

Creates and manages an HA automation that monitors the HEMS heartbeat
via MQTT and activates fallback mode if the heartbeat is lost.

Usage:
    from ha_watchdog import HAWatchdogSetup
    from config import HEMSSettings

    settings = HEMSSettings()
    watchdog = HAWatchdogSetup(ha_url=settings.ha_url, ha_token=settings.hems_ha_token)

    # Provision the automation on startup
    await watchdog.provision_watchdog_automation()

    # Check if automation already exists
    exists = await watchdog.check_automation_exists()
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("hems.ha_watchdog")


class HAWatchdogSetup:
    """Sets up HA automation for HEMS heartbeat monitoring."""

    def __init__(self, ha_url: str, ha_token: str) -> None:
        """Initialize watchdog setup with HA connection details.

        Args:
            ha_url: Base URL for HA (e.g., "http://192.168.0.40:8123")
            ha_token: HA long-lived access token
        """
        self.ha_url = ha_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def check_automation_exists(self) -> bool:
        """Check if the watchdog automation already exists in HA.

        Returns:
            True if automation exists, False otherwise
        """
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.ha_url}/api/config/automation/config/hems_heartbeat_watchdog"
            )
            exists = resp.status_code == 200
            logger.info(
                "automation_exists_check",
                automation_id="hems_heartbeat_watchdog",
                exists=exists,
            )
            return exists
        except Exception as exc:
            logger.exception("automation_check_failed", exc=str(exc))
            return False

    async def provision_watchdog_automation(self) -> dict[str, Any]:
        """Create or update the HEMS heartbeat watchdog automation in HA.

        The automation:
        - Triggers when MQTT topic `homelab/hems/heartbeat/state` becomes unavailable
        - Waits for 300 seconds of payload absence
        - Activates fallback mode by turning on `input_boolean.hems_fallback_mode`
        - Sends a persistent notification

        Returns:
            Response from HA API with automation details

        Raises:
            httpx.HTTPError if automation creation fails
        """
        automation_config = {
            "alias": "HEMS Heartbeat Watchdog",
            "description": "Monitor HEMS heartbeat and activate fallback on loss",
            "triggers": [
                {
                    "platform": "mqtt",
                    "topic": "homelab/hems/heartbeat/state",
                    "payload": "unavailable",
                    "for": {"seconds": 300},
                }
            ],
            "actions": [
                {
                    "service": "input_boolean.turn_on",
                    "data": {"entity_id": "input_boolean.hems_fallback_mode"},
                },
                {
                    "service": "notify.persistent_notification",
                    "data": {
                        "title": "HEMS Watchdog",
                        "message": "HEMS heartbeat lost — fallback mode activated",
                        "notification_id": "hems_watchdog_alert",
                    },
                },
            ],
            "mode": "single",
        }

        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.ha_url}/api/config/automation/config/hems_heartbeat_watchdog",
                json=automation_config,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info(
                "watchdog_automation_provisioned",
                automation_id="hems_heartbeat_watchdog",
                status="created",
            )
            return result
        except httpx.HTTPError as exc:
            logger.exception(
                "watchdog_provision_failed",
                automation_id="hems_heartbeat_watchdog",
                error=str(exc),
            )
            raise
