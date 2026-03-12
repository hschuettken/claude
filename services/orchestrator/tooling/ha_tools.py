"""Home Assistant tool definitions and handlers."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger
from memory import Memory

logger = get_logger("tooling.ha_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_entity_state",
            "description": (
                "Get the current state and attributes of a Home Assistant entity. "
                "Use this to read sensor values, switch states, input helpers, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Full entity ID, e.g. sensor.temperature_living_room",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_ha_entities",
            "description": (
                "List Home Assistant entities with optional filtering by domain and state. "
                "Use this for generic pass-through discovery of everything available in HA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. sensor, light, switch, climate)",
                    },
                    "state": {
                        "type": "string",
                        "description": "Optional exact state filter (e.g. on, off, unavailable)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entities to return (default 200)",
                        "default": 200,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_ha_services",
            "description": (
                "List Home Assistant service domains and services. "
                "Use this to discover callable actions for full HA pass-through control."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. light, switch, climate)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_ha_service",
            "description": (
                "Call a Home Assistant service to control devices. ALWAYS confirm with "
                "the user before calling this — never execute actions without permission. "
                "Examples: light.turn_on, switch.turn_off, input_select.select_option."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Service domain, e.g. light, switch, input_select",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service name, e.g. turn_on, turn_off, select_option",
                    },
                    "data": {
                        "type": "object",
                        "description": "Service data payload (entity_id, etc.)",
                    },
                },
                "required": ["domain", "service"],
            },
        },
    },
]


class HATools:
    """Handlers for Home Assistant tools."""

    def __init__(self, ha: HomeAssistantClient, memory: Memory, activity_tracker: Any = None) -> None:
        self.ha = ha
        self.memory = memory
        self._activity_tracker = activity_tracker

    async def get_entity_state(self, entity_id: str) -> dict[str, Any]:
        state = await self.ha.get_state(entity_id)
        return {
            "entity_id": entity_id,
            "state": state.get("state"),
            "unit": state.get("attributes", {}).get("unit_of_measurement"),
            "friendly_name": state.get("attributes", {}).get("friendly_name"),
            "last_changed": state.get("last_changed"),
            "attributes": {
                k: v
                for k, v in state.get("attributes", {}).items()
                if k in ("hourly", "device_class", "state_class", "options")
            },
        }

    async def list_ha_entities(
        self,
        domain: str | None = None,
        state: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        entities = await self.ha.get_states()
        out: list[dict[str, Any]] = []
        domain_norm = domain.lower() if domain else None
        state_norm = state.lower() if state else None

        for item in entities:
            entity_id = item.get("entity_id", "")
            entity_domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            entity_state = str(item.get("state", ""))

            if domain_norm and entity_domain != domain_norm:
                continue
            if state_norm and entity_state.lower() != state_norm:
                continue

            out.append({
                "entity_id": entity_id,
                "domain": entity_domain,
                "state": entity_state,
                "friendly_name": item.get("attributes", {}).get("friendly_name"),
                "unit": item.get("attributes", {}).get("unit_of_measurement"),
                "last_changed": item.get("last_changed"),
            })

            if len(out) >= max(1, min(limit, 2000)):
                break

        return {
            "count": len(out),
            "filters": {"domain": domain, "state": state, "limit": limit},
            "entities": out,
        }

    async def list_ha_services(self, domain: str | None = None) -> dict[str, Any]:
        services = await self.ha.get_services()
        if domain:
            domain_lower = domain.lower()
            services = [s for s in services if s.get("domain", "").lower() == domain_lower]

        simplified = []
        for d in services:
            svc = d.get("services", {})
            simplified.append({
                "domain": d.get("domain"),
                "services": sorted(list(svc.keys())),
            })

        return {
            "count": len(simplified),
            "domain_filter": domain,
            "domains": simplified,
        }

    async def call_ha_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self.ha.call_service(domain, service, data or {})
        decision_text = f"Called {domain}.{service} with {data}"
        self.memory.log_decision(
            context=f"HA service call: {domain}.{service}",
            decision=decision_text,
            reasoning="User requested via orchestrator",
        )
        if self._activity_tracker:
            self._activity_tracker.record_decision(decision_text)
        return {"success": True, "domain": domain, "service": service}
