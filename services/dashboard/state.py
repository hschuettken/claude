"""Shared state manager for the dashboard.

Collects data from MQTT subscriptions and HA API polling.
All data is stored in plain dicts for thread-safe access from the NiceGUI UI.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from shared.log import get_logger

logger = get_logger("dashboard-state")


class DashboardState:
    """Thread-safe shared state updated by MQTT and HA polling."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Service heartbeats: {service_name: {status, uptime_seconds, ...}}
        self.services: dict[str, dict[str, Any]] = {}

        # Latest MQTT payloads per topic
        self.pv_forecast: dict[str, Any] = {}
        self.ev_charging: dict[str, Any] = {}
        self.ev_forecast_plan: dict[str, Any] = {}
        self.ev_vehicle: dict[str, Any] = {}
        self.orchestrator_activity: dict[str, Any] = {}
        self.health_status: dict[str, Any] = {}

        # HA entity states: {entity_id: {state, attributes, last_updated}}
        self.ha_entities: dict[str, dict[str, Any]] = {}

        # Chat
        self.chat_messages: list[dict[str, Any]] = []
        self.chat_pending: bool = False
        self.chat_pending_id: str = ""

        # Timestamps
        self.last_mqtt_update: float = 0
        self.last_ha_update: float = 0

    # ------------------------------------------------------------------
    # MQTT state updaters
    # ------------------------------------------------------------------

    def update_service(self, service_name: str, data: dict[str, Any]) -> None:
        with self._lock:
            self.services[service_name] = {
                **data,
                "last_seen": time.time(),
            }
            self.last_mqtt_update = time.time()

    def update_pv_forecast(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.pv_forecast = data
            self.last_mqtt_update = time.time()

    def update_ev_charging(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.ev_charging = data
            self.last_mqtt_update = time.time()

    def update_ev_forecast(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.ev_forecast_plan = data
            self.last_mqtt_update = time.time()

    def update_ev_vehicle(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.ev_vehicle = data
            self.last_mqtt_update = time.time()

    def update_orchestrator(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.orchestrator_activity = data
            self.last_mqtt_update = time.time()

    def update_health(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.health_status = data
            self.last_mqtt_update = time.time()

    # ------------------------------------------------------------------
    # HA entity state
    # ------------------------------------------------------------------

    def update_ha_entity(self, entity_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self.ha_entities[entity_id] = data
            self.last_ha_update = time.time()

    def get_entity_state(self, entity_id: str) -> str:
        """Get cached HA entity state string."""
        entity = self.ha_entities.get(entity_id, {})
        return entity.get("state", "unknown")

    def get_entity_float(self, entity_id: str, default: float = 0.0) -> float:
        """Get cached HA entity state as float."""
        try:
            val = self.get_entity_state(entity_id)
            if val in ("unknown", "unavailable", ""):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_entity_attributes(self, entity_id: str) -> dict[str, Any]:
        """Get cached HA entity attributes."""
        entity = self.ha_entities.get(entity_id, {})
        return entity.get("attributes", {})

    def get_entity_options(self, entity_id: str) -> list[str]:
        """Get options for an input_select entity."""
        attrs = self.get_entity_attributes(entity_id)
        return attrs.get("options", [])

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def add_chat_message(self, role: str, content: str) -> None:
        with self._lock:
            self.chat_messages.append({
                "role": role,
                "content": content,
                "timestamp": time.time(),
            })

    def send_chat_request(self) -> str:
        """Mark chat as pending and return a new request ID."""
        request_id = str(uuid.uuid4())[:8]
        with self._lock:
            self.chat_pending = True
            self.chat_pending_id = request_id
        return request_id

    def receive_chat_response(self, request_id: str, response: str) -> None:
        """Handle an incoming chat response."""
        with self._lock:
            if self.chat_pending_id == request_id:
                self.chat_pending = False
                self.chat_pending_id = ""
            self.chat_messages.append({
                "role": "assistant",
                "content": response,
                "timestamp": time.time(),
            })
