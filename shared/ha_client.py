"""Home Assistant API client.

Wraps both REST and WebSocket APIs for convenient use.

Usage:
    from shared.ha_client import HomeAssistantClient
    from shared.config import Settings

    settings = Settings()
    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)

    # Get entity state
    state = await ha.get_state("sensor.temperature_living_room")

    # Call a service
    await ha.call_service("light", "turn_on", {"entity_id": "light.kitchen"})

    # Get all states
    states = await ha.get_states()
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("ha-client")


class HomeAssistantClient:
    """Async Home Assistant REST API client."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.url}/api",
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        """Get the current state of an entity."""
        client = await self._get_client()
        resp = await client.get(f"/states/{entity_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_states(self) -> list[dict[str, Any]]:
        """Get all entity states."""
        client = await self._get_client()
        resp = await client.get("/states")
        resp.raise_for_status()
        return resp.json()

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Call a Home Assistant service."""
        client = await self._get_client()
        resp = await client.post(
            f"/services/{domain}/{service}",
            json=data or {},
        )
        resp.raise_for_status()
        logger.info("service_called", domain=domain, service=service, data=data)
        return resp.json()

    async def fire_event(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> None:
        """Fire a custom event."""
        client = await self._get_client()
        resp = await client.post(
            f"/events/{event_type}",
            json=event_data or {},
        )
        resp.raise_for_status()

    async def get_history(
        self, entity_id: str, start: str | None = None, end: str | None = None
    ) -> list[list[dict[str, Any]]]:
        """Get state history for an entity."""
        params: dict[str, str] = {"filter_entity_id": entity_id}
        if end:
            params["end_time"] = end
        path = f"/history/period/{start}" if start else "/history/period"
        client = await self._get_client()
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
