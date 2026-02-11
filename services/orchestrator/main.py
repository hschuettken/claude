"""Orchestrator service — the intelligent home coordinator.

Combines LLM reasoning, Home Assistant integration, and Telegram
communication to provide an AI-powered smart home brain.

Architecture:
    Brain (LLM + tools) ←→ Telegram (user I/O)
         ↕                       ↕
    Memory (profiles)      Proactive (scheduled)
         ↕
    HA / InfluxDB / MQTT (home state)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from shared.service import BaseService

from brain import Brain
from gcal import GoogleCalendarClient
from channels.telegram import TelegramChannel
from config import OrchestratorSettings
from llm import create_provider
from memory import Memory
from proactive import ProactiveEngine
from semantic_memory import EmbeddingProvider, SemanticMemory
from tools import ToolExecutor

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class ActivityTracker:
    """Tracks orchestrator activity for HA sensor exposure."""

    def __init__(self) -> None:
        self.messages_today: int = 0
        self.tools_today: int = 0
        self.suggestions_today: int = 0
        self.last_message_time: str = ""
        self.last_tool_name: str = ""
        self.last_tool_time: str = ""
        self.last_suggestion: str = ""
        self.last_suggestion_time: str = ""
        self.last_decision: str = ""
        self.last_decision_time: str = ""
        self._last_reset_date: str = ""

    def _maybe_reset_daily(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self.messages_today = 0
            self.tools_today = 0
            self.suggestions_today = 0
            self._last_reset_date = today

    def record_message(self) -> None:
        self._maybe_reset_daily()
        self.messages_today += 1
        self.last_message_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def record_tool_call(self, tool_name: str) -> None:
        self._maybe_reset_daily()
        self.tools_today += 1
        self.last_tool_name = tool_name
        self.last_tool_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def record_suggestion(self, text: str) -> None:
        self._maybe_reset_daily()
        self.suggestions_today += 1
        self.last_suggestion = text[:500]
        self.last_suggestion_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def record_decision(self, text: str) -> None:
        self.last_decision = text[:500]
        self.last_decision_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict[str, Any]:
        self._maybe_reset_daily()
        return {
            "messages_today": self.messages_today,
            "tools_today": self.tools_today,
            "suggestions_today": self.suggestions_today,
            "last_message_time": self.last_message_time,
            "last_tool_name": self.last_tool_name,
            "last_tool_time": self.last_tool_time,
            "last_suggestion": self.last_suggestion,
            "last_suggestion_time": self.last_suggestion_time,
            "last_decision": self.last_decision,
            "last_decision_time": self.last_decision_time,
        }


class OrchestratorService(BaseService):
    name = "orchestrator"

    def __init__(self) -> None:
        super().__init__(settings=OrchestratorSettings())
        self.settings: OrchestratorSettings
        self._activity = ActivityTracker()
        self._service_states: dict[str, dict[str, Any]] = {}
        # Shared EV state — updated by MQTT, read by tools and brain
        self._ev_state: dict = {"plan": None, "pending_clarifications": []}
        self._proactive: ProactiveEngine | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def run(self) -> None:
        self._loop = asyncio.get_event_loop()
        self.mqtt.connect_background()

        # --- Initialize components ---
        memory = Memory(
            max_history=self.settings.max_conversation_history,
            max_decisions=self.settings.max_decisions,
        )

        llm = create_provider(self.settings)
        self.logger.info(
            "llm_provider_initialized",
            provider=self.settings.llm_provider,
        )

        # --- Semantic memory (optional) ---
        semantic: SemanticMemory | None = None
        if self.settings.enable_semantic_memory:
            embedder = EmbeddingProvider(
                provider=self.settings.llm_provider,
                settings=self.settings,
            )
            semantic = SemanticMemory(
                embedder,
                max_entries=self.settings.semantic_memory_max_entries,
                text_max_len=self.settings.semantic_memory_text_max_len,
                recency_weight=self.settings.semantic_memory_recency_weight,
                recency_half_life_days=self.settings.semantic_memory_recency_half_life_days,
            )
            self.logger.info(
                "semantic_memory_enabled",
                entries=semantic.entry_count,
            )
        else:
            self.logger.info("semantic_memory_disabled")

        # --- Google Calendar (optional) ---
        gcal = GoogleCalendarClient(
            credentials_file=self.settings.google_calendar_credentials_file,
            credentials_json=self.settings.google_calendar_credentials_json,
            timezone=self.settings.timezone,
        )
        if gcal.available:
            self.logger.info(
                "google_calendar_enabled",
                family_cal=bool(self.settings.google_calendar_family_id),
                orchestrator_cal=bool(self.settings.google_calendar_orchestrator_id),
            )
        else:
            self.logger.info("google_calendar_disabled", reason="No credentials configured")

        tool_executor = ToolExecutor(
            ha=self.ha,
            influx=self.influx,
            mqtt=self.mqtt,
            memory=memory,
            settings=self.settings,
            gcal=gcal if gcal.available else None,
            semantic=semantic,
            ev_state=self._ev_state,
        )

        brain = Brain(
            llm=llm,
            tool_executor=tool_executor,
            memory=memory,
            settings=self.settings,
            semantic=semantic,
            ev_state=self._ev_state,
        )

        # Wire activity tracking into brain and tool executor
        brain._activity_tracker = self._activity
        tool_executor._activity_tracker = self._activity

        telegram = TelegramChannel(settings=self.settings, brain=brain)

        # Wire up notification callback so tools can send messages
        tool_executor._send_notification = telegram.send_message

        proactive = ProactiveEngine(
            brain=brain,
            telegram=telegram,
            settings=self.settings,
            gcal=gcal if gcal.available else None,
            ev_state=self._ev_state,
        )
        # Wire activity tracker into proactive engine
        proactive._activity_tracker = self._activity
        self._proactive = proactive

        # --- Subscribe to service events via MQTT ---
        self.mqtt.subscribe("homelab/+/heartbeat", self._on_service_heartbeat)
        self.mqtt.subscribe("homelab/+/updated", self._on_service_update)

        # --- Subscribe to EV forecast events ---
        self.mqtt.subscribe(
            "homelab/ev-forecast/plan", self._on_ev_plan,
        )
        self.mqtt.subscribe(
            "homelab/ev-forecast/clarification-needed", self._on_ev_clarification,
        )

        # --- Register HA discovery entities ---
        self._register_ha_discovery()

        # --- Publish initial activity state ---
        self._publish_activity()

        # --- Start activity publishing loop ---
        asyncio.create_task(self._activity_publish_loop())

        # --- Start communication channel ---
        await telegram.start()
        self.logger.info("telegram_channel_started")

        # --- Start proactive engine ---
        await proactive.start(self._shutdown_event)

        self.logger.info("orchestrator_ready")
        self._touch_healthcheck()

        # --- Keep alive until shutdown ---
        await self.wait_for_shutdown()

        # --- Cleanup ---
        await proactive.stop()
        await telegram.stop()
        self.logger.info("orchestrator_stopped")

    # ------------------------------------------------------------------
    # MQTT event handlers
    # ------------------------------------------------------------------

    def _on_service_heartbeat(self, topic: str, payload: dict) -> None:
        """Track heartbeats from other services."""
        service = payload.get("service", "unknown")
        status = payload.get("status", "unknown")
        self._service_states[service] = {
            "status": status,
            "uptime_seconds": payload.get("uptime_seconds", 0),
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.logger.debug("service_heartbeat", service=service, status=status)

    def _on_service_update(self, topic: str, payload: dict) -> None:
        """React to updates from other services (e.g. new PV forecast)."""
        self.logger.debug("service_update", topic=topic)
        self._touch_healthcheck()

    def _on_ev_plan(self, topic: str, payload: dict) -> None:
        """Handle new EV charging plan — update state and trigger calendar events."""
        self._ev_state["plan"] = payload
        self.logger.info(
            "ev_plan_received",
            days=len(payload.get("days", [])),
            total_kwh=payload.get("total_energy_needed_kwh", 0),
        )
        if self._proactive and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._proactive.on_ev_plan_update(payload), self._loop,
            )

    def _on_ev_clarification(self, topic: str, payload: dict) -> None:
        """Handle EV trip clarification request — forward to users via Telegram."""
        clarifications = payload.get("clarifications", [])
        self._ev_state["pending_clarifications"] = clarifications
        self.logger.info(
            "ev_clarification_received", count=len(clarifications),
        )
        if self._proactive and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._proactive.on_ev_clarification_needed(clarifications),
                self._loop,
            )

    # ------------------------------------------------------------------
    # Activity publishing
    # ------------------------------------------------------------------

    async def _activity_publish_loop(self) -> None:
        """Publish activity data to MQTT every 60 seconds."""
        while not self._shutdown_event.is_set():
            try:
                self._publish_activity()
            except Exception:
                self.logger.debug("activity_publish_failed")
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=60,
                )
                break
            except asyncio.TimeoutError:
                pass

    def _publish_activity(self) -> None:
        """Publish current activity state to MQTT for HA sensors."""
        # Count healthy services
        online_services = [
            s for s, state in self._service_states.items()
            if state.get("status") == "online"
        ]
        payload: dict[str, Any] = {
            **self._activity.to_dict(),
            "services_online": len(online_services),
            "services_tracked": list(self._service_states.keys()),
            "proactive_enabled": self.settings.enable_proactive_suggestions,
            "morning_briefing_enabled": self.settings.enable_morning_briefing,
            "evening_briefing_enabled": self.settings.enable_evening_briefing,
            "reasoning": self._compose_reasoning(online_services),
        }
        self.publish("activity", payload)

    # ------------------------------------------------------------------
    # HA MQTT auto-discovery
    # ------------------------------------------------------------------

    def _register_ha_discovery(self) -> None:
        """Register orchestrator entities in Home Assistant."""
        device = {
            "identifiers": ["homelab_orchestrator"],
            "name": "Home Orchestrator",
            "manufacturer": "Homelab",
            "model": "orchestrator",
        }
        node = "orchestrator"
        heartbeat_topic = f"homelab/{self.name}/heartbeat"
        activity_topic = f"homelab/{self.name}/activity"

        # --- Connectivity & uptime ---
        self.mqtt.publish_ha_discovery(
            "binary_sensor", "service_status", node_id=node, config={
                "name": "Orchestrator Status",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": (
                    "{{ 'ON' if value_json.status == 'online' else 'OFF' }}"
                ),
                "device_class": "connectivity",
                "expire_after": 180,
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "uptime", node_id=node, config={
                "name": "Orchestrator Uptime",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": "{{ value_json.uptime_seconds }}",
                "unit_of_measurement": "s",
                "icon": "mdi:timer-outline",
                "entity_category": "diagnostic",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "llm_provider", node_id=node, config={
                "name": "LLM Provider",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": "{{ value_json.llm_provider }}",
                "icon": "mdi:brain",
            },
        )

        # --- Activity sensors ---

        self.mqtt.publish_ha_discovery(
            "sensor", "messages_today", node_id=node, config={
                "name": "Messages Today",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.messages_today }}",
                "icon": "mdi:message-text-outline",
                "state_class": "total_increasing",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "tools_today", node_id=node, config={
                "name": "Tool Calls Today",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.tools_today }}",
                "icon": "mdi:tools",
                "state_class": "total_increasing",
                "entity_category": "diagnostic",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "suggestions_today", node_id=node, config={
                "name": "Suggestions Sent Today",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.suggestions_today }}",
                "icon": "mdi:lightbulb-on-outline",
                "state_class": "total_increasing",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "last_tool_used", node_id=node, config={
                "name": "Last Tool Used",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.last_tool_name }}",
                "icon": "mdi:wrench-outline",
                "entity_category": "diagnostic",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "last_decision", node_id=node, config={
                "name": "Last Decision",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.last_decision[:250] }}",
                "icon": "mdi:scale-balance",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "last_suggestion", node_id=node, config={
                "name": "Last Suggestion",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.last_suggestion[:250] }}",
                "icon": "mdi:lightbulb-alert-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "services_online", node_id=node, config={
                "name": "Services Online",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.services_online }}",
                "icon": "mdi:server-network",
            },
        )

        # --- Reasoning sensor (rich, with JSON attributes) ---

        self.mqtt.publish_ha_discovery(
            "sensor", "reasoning", node_id=node, config={
                "name": "Orchestrator Reasoning",
                "device": device,
                "state_topic": activity_topic,
                "value_template": "{{ value_json.last_decision[:250] }}",
                "json_attributes_topic": activity_topic,
                "json_attributes_template": (
                    '{{ {"full_reasoning": value_json.reasoning, '
                    '"last_decision": value_json.last_decision, '
                    '"last_decision_time": value_json.last_decision_time, '
                    '"last_suggestion": value_json.last_suggestion, '
                    '"last_suggestion_time": value_json.last_suggestion_time, '
                    '"last_tool_name": value_json.last_tool_name, '
                    '"last_tool_time": value_json.last_tool_time, '
                    '"messages_today": value_json.messages_today, '
                    '"tools_today": value_json.tools_today, '
                    '"suggestions_today": value_json.suggestions_today, '
                    '"services_online": value_json.services_online, '
                    '"services_tracked": value_json.services_tracked} | tojson }}'
                ),
                "icon": "mdi:head-cog-outline",
            },
        )

        # --- Proactive feature status ---

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "proactive_enabled", node_id=node, config={
                "name": "Proactive Suggestions",
                "device": device,
                "state_topic": activity_topic,
                "value_template": (
                    "{{ 'ON' if value_json.proactive_enabled else 'OFF' }}"
                ),
                "icon": "mdi:robot-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "morning_briefing_enabled", node_id=node, config={
                "name": "Morning Briefing",
                "device": device,
                "state_topic": activity_topic,
                "value_template": (
                    "{{ 'ON' if value_json.morning_briefing_enabled else 'OFF' }}"
                ),
                "icon": "mdi:weather-sunset-up",
            },
        )

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "evening_briefing_enabled", node_id=node, config={
                "name": "Evening Briefing",
                "device": device,
                "state_topic": activity_topic,
                "value_template": (
                    "{{ 'ON' if value_json.evening_briefing_enabled else 'OFF' }}"
                ),
                "icon": "mdi:weather-sunset-down",
            },
        )

        self.logger.info("ha_discovery_registered", entity_count=15)

    def _compose_reasoning(self, online_services: list[str]) -> str:
        """Compose detailed human-readable reasoning for the orchestrator state."""
        lines: list[str] = []
        activity = self._activity.to_dict()

        lines.append(f"LLM: {self.settings.llm_provider} | Language: {self.settings.household_language}")
        lines.append(
            f"Activity: {activity['messages_today']} messages, "
            f"{activity['tools_today']} tool calls, "
            f"{activity['suggestions_today']} suggestions today"
        )

        if activity["last_decision"]:
            lines.append(f"Last decision: {activity['last_decision'][:200]}")
        if activity["last_suggestion"]:
            lines.append(f"Last suggestion: {activity['last_suggestion'][:200]}")
        if activity["last_tool_name"]:
            lines.append(f"Last tool: {activity['last_tool_name']} at {activity['last_tool_time']}")

        # Service status
        total = len(self._service_states)
        online = len(online_services)
        lines.append(f"Services: {online}/{total} online")
        for svc, state in sorted(self._service_states.items()):
            status = state.get("status", "?")
            uptime_h = state.get("uptime_seconds", 0) / 3600
            lines.append(f"  {svc}: {status} (uptime {uptime_h:.1f}h)")

        # Feature status
        features = []
        if self.settings.enable_proactive_suggestions:
            features.append("proactive")
        if self.settings.enable_morning_briefing:
            features.append("morning-briefing")
        if self.settings.enable_evening_briefing:
            features.append("evening-briefing")
        if self.settings.enable_semantic_memory:
            features.append("semantic-memory")
        lines.append(f"Features: {', '.join(features) if features else 'none'}")

        # EV state
        ev_plan = self._ev_state.get("plan")
        if ev_plan:
            days = ev_plan.get("days", [])
            if days:
                today = days[0]
                lines.append(
                    f"EV plan: {today.get('charge_mode', '?')} | "
                    f"need {today.get('energy_needed_kwh', 0):.1f} kWh today"
                )
        pending = self._ev_state.get("pending_clarifications", [])
        if pending:
            lines.append(f"Pending EV clarifications: {len(pending)}")

        return "\n".join(lines)

    def health_check(self) -> dict[str, Any]:
        """Add LLM provider and activity info to heartbeat."""
        return {
            "llm_provider": self.settings.llm_provider,
            "messages_today": self._activity.messages_today,
            "services_tracked": len(self._service_states),
        }

    # ------------------------------------------------------------------
    # Healthcheck
    # ------------------------------------------------------------------

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(OrchestratorService().start())
