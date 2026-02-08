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
from pathlib import Path

from shared.service import BaseService

from brain import Brain
from channels.telegram import TelegramChannel
from config import OrchestratorSettings
from llm import create_provider
from memory import Memory
from proactive import ProactiveEngine
from tools import ToolExecutor

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class OrchestratorService(BaseService):
    name = "orchestrator"

    def __init__(self) -> None:
        super().__init__(settings=OrchestratorSettings())
        self.settings: OrchestratorSettings

    async def run(self) -> None:
        self.mqtt.connect_background()

        # --- Initialize components ---
        memory = Memory(max_history=self.settings.max_conversation_history)

        llm = create_provider(self.settings)
        self.logger.info(
            "llm_provider_initialized",
            provider=self.settings.llm_provider,
        )

        tool_executor = ToolExecutor(
            ha=self.ha,
            influx=self.influx,
            mqtt=self.mqtt,
            memory=memory,
            settings=self.settings,
        )

        brain = Brain(
            llm=llm,
            tool_executor=tool_executor,
            memory=memory,
            settings=self.settings,
        )

        telegram = TelegramChannel(settings=self.settings, brain=brain)

        # Wire up notification callback so tools can send messages
        tool_executor._send_notification = telegram.send_message

        proactive = ProactiveEngine(
            brain=brain,
            telegram=telegram,
            settings=self.settings,
        )

        # --- Subscribe to service events via MQTT ---
        self.mqtt.subscribe("homelab/+/heartbeat", self._on_service_heartbeat)
        self.mqtt.subscribe("homelab/+/updated", self._on_service_update)

        # --- Register HA discovery entities ---
        self._register_ha_discovery()

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
        self.logger.debug("service_heartbeat", service=service, status=status)

    def _on_service_update(self, topic: str, payload: dict) -> None:
        """React to updates from other services (e.g. new PV forecast)."""
        self.logger.debug("service_update", topic=topic)
        self._touch_healthcheck()

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

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "service_status", node_id=node, config={
                "name": "Orchestrator Status",
                "device": device,
                "state_topic": f"homelab/{self.name}/heartbeat",
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
                "state_topic": f"homelab/{self.name}/heartbeat",
                "value_template": "{{ value_json.uptime_seconds }}",
                "unit_of_measurement": "s",
                "icon": "mdi:timer-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "llm_provider", node_id=node, config={
                "name": "LLM Provider",
                "device": device,
                "state_topic": f"homelab/{self.name}/heartbeat",
                "value_template": "{{ value_json.llm_provider }}",
                "icon": "mdi:brain",
            },
        )

        self.logger.info("ha_discovery_registered", entity_count=3)

    def health_check(self) -> dict[str, str]:
        """Add LLM provider info to heartbeat."""
        return {"llm_provider": self.settings.llm_provider}

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
