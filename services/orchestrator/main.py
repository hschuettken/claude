"""Orchestrator service — headless home coordinator.

Headless mode: no conversational LLM loop, no Telegram channel, no proactive engine.
Service exposes MCP + REST tools and keeps HA/MQTT/Influx plumbing active.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from shared.service import BaseService

from api.server import create_app, start_api_server
from config import OrchestratorSettings
from gcal import GoogleCalendarClient
from knowledge import KnowledgeStore, MemoryDocument
from memory import Memory
from tools import ToolExecutor

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class ActivityTracker:
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

    def record_tool_call(self, tool_name: str) -> None:
        self._maybe_reset_daily()
        self.tools_today += 1
        self.last_tool_name = tool_name
        self.last_tool_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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
        self._ev_state: dict = {"plan": None, "pending_clarifications": []}

    async def run(self) -> None:
        self.mqtt.connect_background()

        memory = Memory(
            max_history=self.settings.max_conversation_history,
            max_decisions=self.settings.max_decisions,
        )

        knowledge: KnowledgeStore | None = None
        memory_doc: MemoryDocument | None = None
        if self.settings.enable_knowledge_store:
            knowledge = KnowledgeStore(mqtt=self.mqtt)
            memory_doc = MemoryDocument(max_size=self.settings.memory_document_max_size)

        gcal = GoogleCalendarClient(
            credentials_file=self.settings.google_calendar_credentials_file,
            credentials_json=self.settings.google_calendar_credentials_json,
            timezone=self.settings.timezone,
        )

        tool_executor = ToolExecutor(
            ha=self.ha,
            influx=self.influx,
            mqtt=self.mqtt,
            memory=memory,
            settings=self.settings,
            gcal=gcal if gcal.available else None,
            semantic=None,
            ev_state=self._ev_state,
            knowledge=knowledge,
            memory_doc=memory_doc,
        )
        tool_executor._activity_tracker = self._activity

        self.mqtt.subscribe("homelab/+/heartbeat", self._on_service_heartbeat)
        self.mqtt.subscribe("homelab/+/updated", self._on_service_update)
        self.mqtt.subscribe("homelab/ev-forecast/plan", self._on_ev_plan)
        self.mqtt.subscribe("homelab/ev-forecast/clarification-needed", self._on_ev_clarification)

        api_task: asyncio.Task | None = None
        if self.settings.orchestrator_api_key:
            api_app = create_app(
                brain=None,
                tool_executor=tool_executor,
                activity=self._activity,
                settings=self.settings,
                service_states=self._service_states,
                start_time=time.monotonic(),
            )
            api_task = asyncio.create_task(
                start_api_server(
                    app=api_app,
                    host=self.settings.orchestrator_api_host,
                    port=self.settings.orchestrator_api_port,
                    shutdown_event=self._shutdown_event,
                ),
            )
            self.logger.info("api_server_started", port=self.settings.orchestrator_api_port)
        else:
            self.logger.info("api_server_disabled", reason="ORCHESTRATOR_API_KEY not set")

        self.logger.info("orchestrator_ready", mode="headless")
        self._touch_healthcheck()

        # Start periodic healthcheck writer (every 30s)
        healthcheck_task = asyncio.create_task(self._healthcheck_loop())

        await self.wait_for_shutdown()

        # Cancel background tasks
        healthcheck_task.cancel()
        try:
            await healthcheck_task
        except asyncio.CancelledError:
            pass

        if api_task and not api_task.done():
            api_task.cancel()
            try:
                await api_task
            except asyncio.CancelledError:
                pass

        self.logger.info("orchestrator_stopped")

    def _on_service_heartbeat(self, topic: str, payload: dict) -> None:
        service = payload.get("service", "unknown")
        status = payload.get("status", "unknown")
        self._service_states[service] = {
            "status": status,
            "uptime_seconds": payload.get("uptime_seconds", 0),
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _on_service_update(self, topic: str, payload: dict) -> None:
        self._touch_healthcheck()

    def _on_ev_plan(self, topic: str, payload: dict) -> None:
        self._ev_state["plan"] = payload

    def _on_ev_clarification(self, topic: str, payload: dict) -> None:
        self._ev_state["pending_clarifications"] = payload.get("clarifications", [])

    def health_check(self) -> dict[str, Any]:
        return {
            "llm_provider": "headless",
            "messages_today": self._activity.messages_today,
            "services_tracked": len(self._service_states),
        }

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass

    async def _healthcheck_loop(self) -> None:
        """Periodic healthcheck writer — updates timestamp every 30s."""
        while True:
            await asyncio.sleep(30)
            self._touch_healthcheck()


if __name__ == "__main__":
    asyncio.run(OrchestratorService().start())
