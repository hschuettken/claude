"""ToolExecutor — dispatches LLM tool calls to domain-specific handlers."""

from __future__ import annotations

import inspect
import json
from typing import Any

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.mqtt_client import MQTTClient
from shared.log import get_logger

from gcal import GoogleCalendarClient
from config import OrchestratorSettings
from knowledge import KnowledgeStore, MemoryDocument
from memory import Memory
from semantic_memory import SemanticMemory

from tooling.ha_tools import HATools
from tooling.energy_tools import EnergyTools
from tooling.calendar_tools import CalendarTools
from tooling.ev_tools import EVTools
from tooling.memory_tools import MemoryTools
from tooling.notification_tools import NotificationTools
from tooling.orbit_tools import OrbitTools

logger = get_logger("tooling.executor")


class ToolExecutor:
    """Executes LLM tool calls against HA, InfluxDB, MQTT, and memory.

    Delegates each tool to the appropriate domain handler class.
    Maintains full backward compatibility with the original monolithic ToolExecutor.
    """

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
        # Injected by OrchestratorService after construction
        self._activity_tracker: Any = None

        # Domain handler instances — wired up below; activity_tracker set later
        self._ha_tools = HATools(ha=ha, memory=memory)
        self._energy_tools = EnergyTools(ha=ha, influx=influx, settings=settings)
        self._calendar_tools = CalendarTools(gcal=gcal, settings=settings, memory=memory)
        self._ev_tools = EVTools(
            ha=ha,
            mqtt=mqtt,
            settings=settings,
            memory=memory,
            ev_state=self._ev_state,
            knowledge=knowledge,
        )
        self._memory_tools = MemoryTools(
            memory=memory,
            semantic=semantic,
            knowledge=knowledge,
            memory_doc=memory_doc,
        )
        self._notification_tools = NotificationTools(send_notification_fn=send_notification_fn)
        self._orbit_tools = OrbitTools()

        # Build dispatch table: tool_name → (handler_instance, method_name)
        self._dispatch: dict[str, tuple[Any, str]] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Build the tool-name → handler dispatch table."""
        # HA tools
        for name in ("get_entity_state", "list_ha_entities", "list_ha_services", "call_ha_service"):
            self._dispatch[name] = (self._ha_tools, name)

        # Energy tools
        for name in ("get_home_energy_summary", "get_pv_forecast", "get_energy_prices", "query_energy_history"):
            self._dispatch[name] = (self._energy_tools, name)

        # Calendar tools
        for name in ("get_calendar_events", "check_household_availability", "create_calendar_event"):
            self._dispatch[name] = (self._calendar_tools, name)

        # EV tools
        for name in (
            "get_ev_charging_status",
            "set_ev_charge_mode",
            "get_ev_forecast_plan",
            "respond_to_ev_trip_clarification",
            "request_service_refresh",
        ):
            self._dispatch[name] = (self._ev_tools, name)

        # Memory tools
        for name in (
            "get_user_preferences",
            "set_user_preference",
            "recall_memory",
            "store_fact",
            "store_learned_fact",
            "get_learned_facts",
            "update_memory_notes",
            "read_memory_notes",
        ):
            self._dispatch[name] = (self._memory_tools, name)

        # Notification tools
        self._dispatch["send_notification"] = (self._notification_tools, "send_notification")

        # Orbit tools
        for name in (
            "orbit_create_task",
            "orbit_list_tasks",
            "orbit_complete_task",
            "orbit_list_projects",
            "orbit_create_page",
            "orbit_get_recommendations",
            "orbit_what_now",
            "orbit_list_lists",
            "orbit_get_list",
            "orbit_add_list_item",
            "orbit_check_list_item",
        ):
            self._dispatch[name] = (self._orbit_tools, name)

        # Weather (inline on self — uses HA directly)
        self._dispatch["get_weather_forecast"] = (self, "_impl_get_weather_forecast")

    def _propagate_activity_tracker(self) -> None:
        """Push the activity_tracker to handlers that need it."""
        self._ha_tools._activity_tracker = self._activity_tracker
        self._ev_tools._activity_tracker = self._activity_tracker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return a JSON-serializable result string."""
        entry = self._dispatch.get(tool_name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        handler_obj, method_name = entry
        handler = getattr(handler_obj, method_name, None)
        if not handler:
            return json.dumps({"error": f"Handler method not found: {method_name}"})

        try:
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
    # Inline handler: weather (uses HA client directly)
    # ------------------------------------------------------------------

    async def _impl_get_weather_forecast(self) -> dict[str, Any]:
        candidates = [
            self.settings.weather_entity,
            "weather.home",
            "weather.forecast_home",
            "weather.forecast_home_2",
            "weather.openweathermap",
        ]

        last_error: str | None = None
        for entity_id in dict.fromkeys(candidates):
            if not entity_id:
                continue
            try:
                state = await self.ha.get_state(entity_id)
                condition = state.get("state")
                attrs = state.get("attributes", {})

                if condition in (None, "unknown", "unavailable"):
                    continue

                return {
                    "entity_id": entity_id,
                    "current_condition": condition,
                    "temperature": attrs.get("temperature"),
                    "humidity": attrs.get("humidity"),
                    "wind_speed": attrs.get("wind_speed"),
                    "forecast": attrs.get("forecast", [])[:8],
                }
            except Exception as exc:
                last_error = str(exc)
                continue

        if last_error:
            return {"error": f"Weather entity not available: {last_error}"}
        return {"error": "Weather entity not available"}
