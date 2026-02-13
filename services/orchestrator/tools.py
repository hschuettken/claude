"""LLM tool definitions and execution.

Each tool is a function the LLM can call to interact with the home.
Tools are defined in OpenAI-compatible JSON Schema and executed here.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.mqtt_client import MQTTClient

from gcal import GoogleCalendarClient
from config import OrchestratorSettings
from knowledge import KnowledgeStore, MemoryDocument
from memory import Memory
from semantic_memory import SemanticMemory

logger = get_logger("tools")

# ------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ------------------------------------------------------------------

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
            "name": "get_home_energy_summary",
            "description": (
                "Get a comprehensive snapshot of the home's current energy state: "
                "PV production, grid power, battery, EV charging, house consumption, "
                "PV forecast, and energy prices."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pv_forecast",
            "description": (
                "Get the PV solar production forecast for today and tomorrow in kWh, "
                "including per-hour breakdown if available."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ev_charging_status",
            "description": (
                "Get the current EV charging status: charge mode, power, session energy, "
                "departure time, target energy, and whether Full-by-Morning is enabled."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_ev_charge_mode",
            "description": (
                "Change the EV charge mode. ALWAYS confirm with the user before calling this. "
                "Available modes: Off, PV Surplus, Smart, Eco, Fast, Manual."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["Off", "PV Surplus", "Smart", "Eco", "Fast", "Manual"],
                        "description": "The charge mode to set",
                    },
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Get the current weather and short-term forecast from Home Assistant.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_energy_history",
            "description": (
                "Query historical energy data from InfluxDB. Returns hourly averages "
                "for the specified sensor over a time range. Use for trends and analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "HA entity ID, e.g. sensor.inverter_pv_east_energy",
                    },
                    "range_start": {
                        "type": "string",
                        "description": "Flux duration like '-24h', '-7d', '-30d'",
                        "default": "-24h",
                    },
                    "window": {
                        "type": "string",
                        "description": "Aggregation window like '1h', '1d'",
                        "default": "1h",
                    },
                },
                "required": ["entity_id"],
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
    {
        "type": "function",
        "function": {
            "name": "get_user_preferences",
            "description": (
                "Retrieve stored preferences for a user. Use to personalize responses "
                "and suggestions based on known habits and settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user's chat ID or name",
                    },
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_user_preference",
            "description": (
                "Store a user preference for future reference. Examples: "
                "sauna_days=['friday','saturday'], wake_time='06:30', "
                "ev_departure_weekday='07:30', preferred_room_temp=21."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user's chat ID",
                    },
                    "key": {
                        "type": "string",
                        "description": "Preference key (snake_case)",
                    },
                    "value": {
                        "type": "string",
                        "description": "Preference value (will be parsed as JSON if possible)",
                    },
                },
                "required": ["user_id", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": (
                "Send a Telegram notification to a specific user by chat ID. "
                "Use this for proactive alerts or forwarding info to another household member."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "Telegram chat ID of the recipient",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text to send",
                    },
                },
                "required": ["chat_id", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_energy_prices",
            "description": (
                "Get current energy prices: grid buy price, feed-in tariff, "
                "EPEX spot price if available, and oil heating cost."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": (
                "Get upcoming events from a household calendar. Use 'family' for the "
                "shared family calendar (absences, business trips, appointments) or "
                "'orchestrator' for the orchestrator's own calendar (reminders, scheduled actions). "
                "Useful for checking if someone is home, planning energy usage around absences, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {
                        "type": "string",
                        "enum": ["family", "orchestrator"],
                        "description": "Which calendar to read",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days ahead to look (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["calendar"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_household_availability",
            "description": (
                "Check the family calendar to determine who is home today and the next few days. "
                "Looks for absences, business trips, and vacations. "
                "Use this for energy planning (no EV charging if owner is away, "
                "lower heating if nobody home, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days to check (default: 3)",
                        "default": 3,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ev_forecast_plan",
            "description": (
                "Get the current EV driving forecast and charging plan from the ev-forecast "
                "service. Shows predicted trips (who, where, when, km), energy needs per day, "
                "charging urgency, and recommended charge modes for the next 3 days. "
                "This is the demand-side plan — the smart-ev-charging service handles wallbox control."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond_to_ev_trip_clarification",
            "description": (
                "Respond to a pending EV trip clarification from the ev-forecast service. "
                "When the service is unsure whether someone will use the EV for a trip "
                "(e.g., Henning for medium-distance trips), it sends a question via Telegram. "
                "Use this tool to forward the user's answer back to the ev-forecast service."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event_id from the pending clarification",
                    },
                    "use_ev": {
                        "type": "boolean",
                        "description": "Whether the person will use the EV for this trip",
                    },
                    "distance_km": {
                        "type": "number",
                        "description": "One-way distance in km (if the user provides it, otherwise 0)",
                        "default": 0,
                    },
                },
                "required": ["event_id", "use_ev"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Create an event on the orchestrator's calendar. Use for reminders, "
                "scheduled energy actions, or notes. ALWAYS confirm with the user before creating. "
                "Only writes to the orchestrator calendar, never to the family calendar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time in ISO 8601 format (e.g. 2025-01-15T17:00:00+01:00) or YYYY-MM-DD for all-day",
                    },
                    "end": {
                        "type": "string",
                        "description": "End time in ISO 8601 format or YYYY-MM-DD for all-day",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description/notes",
                    },
                    "all_day": {
                        "type": "boolean",
                        "description": "Whether this is an all-day event (default: false)",
                        "default": False,
                    },
                },
                "required": ["summary", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Search your long-term semantic memory for relevant past conversations, "
                "learned facts, and previous decisions. Use this when the user references "
                "something from the past ('last time', 'remember when', 'as I said before') "
                "or when you need historical context to answer a question better."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to search for — a natural-language description of the "
                            "information you need (e.g. 'Henning sauna preferences', "
                            "'EV charging decisions last week', 'Nicole business trips')."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["conversation", "fact", "decision"],
                        "description": (
                            "Optional category filter: 'conversation' for past exchanges, "
                            "'fact' for stored knowledge, 'decision' for past orchestrator decisions."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_fact",
            "description": (
                "Store an important fact, user preference, or piece of knowledge in long-term "
                "semantic memory. Use this when you learn something worth remembering across "
                "conversations — e.g. user habits, important decisions, household rules. "
                "This is different from set_user_preference (key-value pairs) — store_fact "
                "stores free-text knowledge that can be semantically searched later."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The fact or knowledge to store. Be specific and include context. "
                            "Example: 'Henning prefers to charge the EV overnight when electricity "
                            "is cheaper, unless there is enough PV forecast for tomorrow.'"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["fact", "decision"],
                        "description": "Category: 'fact' for knowledge, 'decision' for orchestrator decisions",
                        "default": "fact",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_learned_fact",
            "description": (
                "Store a structured, typed fact in the knowledge store. Use this when you "
                "learn something concrete and actionable from a conversation: a destination "
                "with distance, a person's behavioral pattern, a user preference, or a "
                "correction to previous knowledge. This is different from store_fact (free-text "
                "semantic memory) — store_learned_fact creates a structured, queryable entry "
                "that other services (ev-forecast, smart-ev-charging) can use to improve "
                "their behavior automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": ["destination", "person_pattern", "preference", "correction", "general"],
                        "description": (
                            "Type of fact: 'destination' (place + distance), "
                            "'person_pattern' (behavioral pattern for a person), "
                            "'preference' (user preference), 'correction' (fix to previous knowledge), "
                            "'general' (other structured knowledge)"
                        ),
                    },
                    "key": {
                        "type": "string",
                        "description": (
                            "Normalised lookup key. For destinations: 'sarah_ibbenbüren' or 'münchen'. "
                            "For patterns: 'henning_berlin_train'. For preferences: 'henning_charge_overnight'."
                        ),
                    },
                    "data": {
                        "type": "object",
                        "description": (
                            "Type-specific data. Destination: {name, distance_km, person, disambiguation, notes}. "
                            "Pattern: {person, pattern, context}. Preference: {user, value, context}. "
                            "Correction: {original, corrected, context}."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence: 1.0 = user explicitly confirmed, 0.7 = inferred from conversation",
                        "default": 1.0,
                    },
                },
                "required": ["fact_type", "key", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_learned_facts",
            "description": (
                "Search the knowledge store for previously learned structured facts. "
                "Use this to check what the system already knows before asking the user "
                "a question (e.g., check known destinations before asking about a trip, "
                "check person patterns before suggesting a charge mode)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": ["destination", "person_pattern", "preference", "correction", "general"],
                        "description": "Filter by fact type (optional — omit to search all types)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search term — matches against key and data values (optional)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory_notes",
            "description": (
                "Update the orchestrator's persistent memory notes (memory.md). "
                "This is your personal notebook — a living document where you maintain "
                "everything you've learned about the household, destinations, preferences, "
                "patterns, and rules. The current content is shown in your system prompt "
                "under '## Memory Notes'. When you learn something new, update the relevant "
                "section. Keep it concise and well-organized — it's injected into every "
                "conversation. Write the COMPLETE updated document (you'll see the current "
                "content in context)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "The full updated memory.md content. Markdown format. "
                            "Include all sections, not just the changed part."
                        ),
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory_notes",
            "description": (
                "Read the current content of the memory notes (memory.md). "
                "Use this if you need to check the full document before updating it, "
                "or if the system prompt excerpt was truncated."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_service_refresh",
            "description": (
                "Send a command to one of the homelab services to trigger an immediate refresh. "
                "Use when the user asks for up-to-date data or when you need fresh data before "
                "answering a question. Available services: pv-forecast, smart-ev-charging, ev-forecast. "
                "Available commands: 'refresh' (update forecast/plan/cycle), "
                "'retrain' (pv-forecast only: retrain ML model), "
                "'refresh_vehicle' (ev-forecast only: refresh Audi Connect data)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["pv-forecast", "smart-ev-charging", "ev-forecast"],
                        "description": "The service to send the command to",
                    },
                    "command": {
                        "type": "string",
                        "enum": ["refresh", "retrain", "refresh_vehicle"],
                        "description": "The command to send",
                        "default": "refresh",
                    },
                },
                "required": ["service"],
            },
        },
    },
]


# ------------------------------------------------------------------
# Tool executor
# ------------------------------------------------------------------


class ToolExecutor:
    """Executes LLM tool calls against HA, InfluxDB, MQTT, and memory."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        influx: InfluxClient,
        mqtt: MQTTClient,
        memory: Memory,
        settings: OrchestratorSettings,
        gcal: GoogleCalendarClient | None = None,
        semantic: SemanticMemory | None = None,
        send_notification_fn: Any = None,
        ev_state: dict[str, Any] | None = None,
        knowledge: KnowledgeStore | None = None,
        memory_doc: MemoryDocument | None = None,
    ) -> None:
        self.ha = ha
        self.influx = influx
        self.mqtt = mqtt
        self.memory = memory
        self.settings = settings
        self.gcal = gcal
        self.semantic = semantic
        self._send_notification = send_notification_fn
        self._ev_state = ev_state or {}
        self._knowledge = knowledge
        self._memory_doc = memory_doc
        self._tz = ZoneInfo(settings.timezone)
        # Injected by OrchestratorService after construction
        self._activity_tracker: Any = None

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return a JSON-serializable result string."""
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            # Filter out arguments the handler doesn't accept (LLMs sometimes
            # hallucinate extra parameters not in the tool schema).
            sig = inspect.signature(handler)
            params = sig.parameters
            if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
                valid_names = set(params.keys())
                filtered = {k: v for k, v in arguments.items() if k in valid_names}
                if len(filtered) != len(arguments):
                    dropped = set(arguments) - valid_names
                    logger.warning("tool_args_filtered", tool=tool_name, dropped=list(dropped))
                arguments = filtered

            result = await handler(**arguments)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.exception("tool_execution_error", tool=tool_name)
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _tool_get_entity_state(self, entity_id: str) -> dict[str, Any]:
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

    async def _tool_get_home_energy_summary(self) -> dict[str, Any]:
        s = self.settings
        reads = await asyncio.gather(
            self._read_float(s.pv_power_entity),
            self._read_float(s.grid_power_entity),
            self._read_float(s.house_power_entity),
            self._read_float(s.battery_power_entity),
            self._read_float(s.battery_soc_entity),
            self._read_float(s.ev_power_entity),
            self._read_float(s.pv_forecast_today_entity),
            self._read_float(s.pv_forecast_today_remaining_entity),
            self._read_float(s.pv_forecast_tomorrow_entity),
            return_exceptions=True,
        )

        def val(i: int) -> float | str:
            r = reads[i]
            return round(r, 1) if isinstance(r, (int, float)) else "unavailable"

        now = datetime.now(self._tz)
        grid_w = val(1)
        grid_direction = "unknown"
        if isinstance(grid_w, (int, float)):
            grid_direction = "exporting" if grid_w > 0 else "importing"

        return {
            "timestamp": now.isoformat(),
            "pv_production_w": val(0),
            "grid_power_w": grid_w,
            "grid_direction": grid_direction,
            "house_consumption_w": val(2),
            "battery_power_w": val(3),
            "battery_note": "positive=charging, negative=discharging",
            "battery_soc_pct": val(4),
            "ev_charging_w": val(5),
            "pv_forecast_today_kwh": val(6),
            "pv_forecast_remaining_kwh": val(7),
            "pv_forecast_tomorrow_kwh": val(8),
            "grid_price_ct_kwh": s.grid_price_ct,
            "feed_in_ct_kwh": s.feed_in_tariff_ct,
        }

    async def _tool_get_pv_forecast(self) -> dict[str, Any]:
        s = self.settings
        entities = [
            s.pv_forecast_today_entity,
            s.pv_forecast_today_remaining_entity,
            s.pv_forecast_tomorrow_entity,
        ]
        results: dict[str, Any] = {}
        for entity in entities:
            try:
                state = await self.ha.get_state(entity)
                results[entity] = {
                    "value": state.get("state"),
                    "unit": state.get("attributes", {}).get("unit_of_measurement"),
                    "hourly": state.get("attributes", {}).get("hourly"),
                }
            except Exception:
                results[entity] = {"value": "unavailable"}
        return results

    async def _tool_get_ev_charging_status(self) -> dict[str, Any]:
        s = self.settings
        reads = await asyncio.gather(
            self.ha.get_state(s.ev_charge_mode_entity),
            self._read_float(s.ev_power_entity),
            self._read_float(s.ev_energy_entity),
            self.ha.get_state(s.ev_departure_time_entity),
            self._read_float(s.ev_target_energy_entity),
            return_exceptions=True,
        )

        def safe_state(i: int) -> str:
            r = reads[i]
            if isinstance(r, dict):
                return r.get("state", "unknown")
            if isinstance(r, (int, float)):
                return str(r)
            return "unavailable"

        return {
            "charge_mode": safe_state(0),
            "current_power_w": safe_state(1),
            "session_energy_kwh": safe_state(2),
            "departure_time": safe_state(3),
            "target_energy_kwh": safe_state(4),
        }

    async def _tool_set_ev_charge_mode(self, mode: str) -> dict[str, Any]:
        await self.ha.call_service(
            "input_select",
            "select_option",
            {
                "entity_id": self.settings.ev_charge_mode_entity,
                "option": mode,
            },
        )
        decision_text = f"Set EV charge mode to {mode}"
        self.memory.log_decision(
            context="EV charge mode change",
            decision=decision_text,
            reasoning="User requested via orchestrator",
        )
        if self._activity_tracker:
            self._activity_tracker.record_decision(decision_text)
        return {"success": True, "mode": mode}

    async def _tool_get_weather_forecast(self) -> dict[str, Any]:
        try:
            state = await self.ha.get_state(self.settings.weather_entity)
            attrs = state.get("attributes", {})
            return {
                "current_condition": state.get("state"),
                "temperature": attrs.get("temperature"),
                "humidity": attrs.get("humidity"),
                "wind_speed": attrs.get("wind_speed"),
                "forecast": attrs.get("forecast", [])[:8],  # next 8 periods
            }
        except Exception:
            return {"error": "Weather entity not available"}

    async def _tool_query_energy_history(
        self,
        entity_id: str,
        range_start: str = "-24h",
        window: str = "1h",
    ) -> dict[str, Any]:
        # Run sync InfluxDB query in thread pool
        records = await asyncio.to_thread(
            self.influx.query_mean,
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start=range_start,
            window=window,
        )
        # Simplify output for the LLM
        simplified = [
            {
                "time": str(r.get("_time", "")),
                "value": round(r.get("_value", 0), 2) if r.get("_value") is not None else None,
            }
            for r in records
        ]
        return {
            "entity_id": entity_id,
            "range": range_start,
            "window": window,
            "record_count": len(simplified),
            "data": simplified[:100],  # cap at 100 points
        }

    async def _tool_call_ha_service(
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

    async def _tool_get_user_preferences(self, user_id: str) -> dict[str, Any]:
        prefs = self.memory.get_all_preferences(user_id)
        name = self.memory.get_user_name(user_id)
        return {"user_id": user_id, "name": name, "preferences": prefs}

    async def _tool_set_user_preference(
        self, user_id: str, key: str, value: str
    ) -> dict[str, Any]:
        # Try to parse value as JSON (for lists, numbers, booleans)
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value
        self.memory.set_preference(user_id, key, parsed)
        return {"success": True, "user_id": user_id, "key": key, "value": parsed}

    async def _tool_send_notification(
        self, chat_id: str, message: str
    ) -> dict[str, Any]:
        if self._send_notification:
            await self._send_notification(int(chat_id), message)
            return {"success": True, "chat_id": chat_id}
        return {"error": "Notification channel not available"}

    async def _tool_get_calendar_events(
        self, calendar: str, days_ahead: int = 3,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = ""
        if calendar == "family":
            cal_id = self.settings.google_calendar_family_id
        elif calendar == "orchestrator":
            cal_id = self.settings.google_calendar_orchestrator_id

        if not cal_id:
            return {"error": f"Calendar '{calendar}' not configured (no calendar ID set)"}

        events = await self.gcal.get_events(
            calendar_id=cal_id,
            days_ahead=days_ahead,
            max_results=25,
        )
        return {
            "calendar": calendar,
            "days_ahead": days_ahead,
            "event_count": len(events),
            "events": events,
        }

    async def _tool_check_household_availability(
        self, days_ahead: int = 3,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = self.settings.google_calendar_family_id
        if not cal_id:
            return {"error": "Family calendar not configured (GOOGLE_CALENDAR_FAMILY_ID)"}

        events = await self.gcal.get_events(
            calendar_id=cal_id,
            days_ahead=days_ahead,
            max_results=30,
        )

        # Look for absence-related keywords in event summaries
        absence_keywords = {
            "abwesend", "absent", "away", "trip", "reise", "dienstreise",
            "business trip", "urlaub", "vacation", "holiday", "unterwegs",
            "nicht da", "verreist",
        }
        absences: list[dict[str, Any]] = []
        other_events: list[dict[str, Any]] = []

        for event in events:
            summary_lower = (event.get("summary") or "").lower()
            if any(kw in summary_lower for kw in absence_keywords) or event.get("all_day"):
                absences.append(event)
            else:
                other_events.append(event)

        now = datetime.now(self._tz)
        return {
            "check_date": now.strftime("%Y-%m-%d"),
            "days_checked": days_ahead,
            "absences": absences,
            "absence_count": len(absences),
            "other_events": other_events[:10],
            "hint": (
                "Absences include events with keywords like 'Dienstreise', 'Urlaub', "
                "'away', or all-day events. Check event summaries for who is absent."
            ),
        }

    async def _tool_create_calendar_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        all_day: bool = False,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = self.settings.google_calendar_orchestrator_id
        if not cal_id:
            return {"error": "Orchestrator calendar not configured (GOOGLE_CALENDAR_ORCHESTRATOR_ID)"}

        event = await self.gcal.create_event(
            calendar_id=cal_id,
            summary=summary,
            start=start,
            end=end,
            description=description,
            all_day=all_day,
        )
        self.memory.log_decision(
            context="Calendar event created",
            decision=f"Created '{summary}' on {start}",
            reasoning="User requested via orchestrator",
        )
        return {"success": True, "event": event}

    async def _tool_get_ev_forecast_plan(self) -> dict[str, Any]:
        plan = self._ev_state.get("plan")
        if not plan:
            return {
                "error": (
                    "No EV forecast plan available. "
                    "The ev-forecast service may not be running."
                ),
            }
        return plan

    async def _tool_respond_to_ev_trip_clarification(
        self,
        event_id: str,
        use_ev: bool,
        distance_km: float = 0,
    ) -> dict[str, Any]:
        self.mqtt.publish("homelab/ev-forecast/trip-response", {
            "event_id": event_id,
            "use_ev": use_ev,
            "distance_km": distance_km,
        })

        # Find the clarification details for logging
        pending = self._ev_state.get("pending_clarifications", [])
        clarification = next(
            (c for c in pending if c.get("event_id") == event_id), {},
        )
        # Remove resolved clarification from state
        self._ev_state["pending_clarifications"] = [
            c for c in pending if c.get("event_id") != event_id
        ]

        person = clarification.get("person", "?")
        destination = clarification.get("destination", "?")
        action = "uses" if use_ev else "does not use"

        self.memory.log_decision(
            context=f"EV trip clarification: {person} \u2192 {destination}",
            decision=f"{person} {action} EV for trip to {destination}",
            reasoning=f"User confirmed via Telegram (distance: {distance_km} km)",
        )

        # --- Auto-learn: store destination and pattern in knowledge store ---
        if self._knowledge and destination != "?":
            # Store destination distance if provided
            if distance_km > 0:
                dest_key = destination.lower().strip()
                self._knowledge.store(
                    fact_type="destination",
                    key=dest_key,
                    data={
                        "name": destination,
                        "distance_km": distance_km,
                        "person": person,
                        "notes": f"Learned from trip clarification ({person})",
                    },
                    confidence=1.0,
                    source="trip_clarification",
                )
            # Store person pattern (e.g., "Henning does not use EV for Berlin")
            if not use_ev:
                pattern_key = f"{person.lower()}_{destination.lower().strip()}_no_ev"
                self._knowledge.store(
                    fact_type="person_pattern",
                    key=pattern_key,
                    data={
                        "person": person,
                        "pattern": f"does not use EV for trips to {destination}",
                        "destination": destination,
                        "context": "User confirmed via trip clarification",
                    },
                    confidence=1.0,
                    source="trip_clarification",
                )

        return {
            "success": True,
            "event_id": event_id,
            "person": person,
            "destination": destination,
            "use_ev": use_ev,
            "distance_km": distance_km,
        }

    async def _tool_get_energy_prices(self) -> dict[str, Any]:
        s = self.settings
        result: dict[str, Any] = {
            "grid_buy_ct_kwh": s.grid_price_ct,
            "feed_in_ct_kwh": s.feed_in_tariff_ct,
            "oil_heating_ct_kwh": s.oil_price_per_kwh_ct,
        }
        try:
            epex = await self.ha.get_state(s.epex_price_entity)
            result["epex_spot_ct_kwh"] = epex.get("state")
            result["epex_attributes"] = {
                k: v
                for k, v in epex.get("attributes", {}).items()
                if k in ("data", "unit_of_measurement")
            }
        except Exception:
            result["epex_spot_ct_kwh"] = "unavailable"
        return result

    async def _tool_recall_memory(
        self, query: str, category: str | None = None, top_k: int = 5,
    ) -> dict[str, Any]:
        if not self.semantic:
            return {"error": "Semantic memory not enabled"}
        results = await self.semantic.search(query, top_k=top_k, category=category)
        return {
            "query": query,
            "result_count": len(results),
            "memories": results,
            "total_stored": self.semantic.entry_count,
        }

    async def _tool_store_fact(
        self, text: str, category: str = "fact",
    ) -> dict[str, Any]:
        if not self.semantic:
            return {"error": "Semantic memory not enabled"}
        entry_id = await self.semantic.store(text, category=category)
        if not entry_id:
            return {"error": "Failed to store — embedding provider unavailable"}
        return {
            "success": True,
            "id": entry_id,
            "category": category,
            "total_stored": self.semantic.entry_count,
        }

    async def _tool_request_service_refresh(
        self, service: str, command: str = "refresh",
    ) -> dict[str, Any]:
        topic = f"homelab/orchestrator/command/{service}"
        self.mqtt.publish(topic, {"command": command})
        logger.info("service_command_sent", service=service, command=command)
        return {
            "success": True,
            "service": service,
            "command": command,
            "note": f"Command '{command}' sent to {service}. The service will process it asynchronously.",
        }

    # ------------------------------------------------------------------
    # Knowledge store + memory document tools
    # ------------------------------------------------------------------

    async def _tool_store_learned_fact(
        self,
        fact_type: str,
        key: str,
        data: dict[str, Any],
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        if not self._knowledge:
            return {"error": "Knowledge store not enabled"}
        try:
            fact_id = self._knowledge.store(
                fact_type=fact_type,
                key=key,
                data=data,
                confidence=confidence,
                source="conversation",
            )
            return {
                "success": True,
                "id": fact_id,
                "fact_type": fact_type,
                "key": key,
                "total_facts": self._knowledge.count,
            }
        except ValueError as e:
            return {"error": str(e)}

    async def _tool_get_learned_facts(
        self,
        fact_type: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        if not self._knowledge:
            return {"error": "Knowledge store not enabled"}
        results = self._knowledge.search(fact_type=fact_type, query=query)
        # Return concise view (skip internal fields)
        facts = [
            {
                "id": f["id"],
                "type": f["type"],
                "key": f["key"],
                "data": f["data"],
                "confidence": f["confidence"],
                "source": f["source"],
                "times_used": f["times_used"],
            }
            for f in results[:20]
        ]
        return {
            "query": query or "(all)",
            "fact_type": fact_type or "all",
            "result_count": len(facts),
            "facts": facts,
            "total_stored": self._knowledge.count,
        }

    async def _tool_update_memory_notes(self, content: str) -> dict[str, Any]:
        if not self._memory_doc:
            return {"error": "Memory document not enabled"}
        success = self._memory_doc.write(content)
        if success:
            return {
                "success": True,
                "size": len(content),
                "note": "Memory notes updated. Changes will be visible in the next conversation.",
            }
        return {"error": "Failed to write memory document"}

    async def _tool_read_memory_notes(self) -> dict[str, Any]:
        if not self._memory_doc:
            return {"error": "Memory document not enabled"}
        content = self._memory_doc.read()
        return {"content": content, "size": len(content)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _read_float(self, entity_id: str, default: float = 0.0) -> float:
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", str(default))
            if val in ("unavailable", "unknown"):
                return default
            return float(val)
        except Exception:
            return default
