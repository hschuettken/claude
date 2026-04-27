"""EV-specific tool definitions and handlers."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger
from config import OrchestratorSettings
from memory import Memory
from knowledge import KnowledgeStore

logger = get_logger("tooling.ev_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
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
            "name": "set_ev_ready_by",
            "description": (
                "Set the EV to be ready by a specific time with a target state of charge. "
                "Use when the user says something like 'I need to leave at 06:30 with 80%'. "
                "Switches the charger into Ready By mode, sets the deadline + target SoC HA "
                "helpers, triggers an immediate replan in ev-forecast, and returns confirmation "
                "plus the resulting plan summary once acknowledged."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "deadline_local": {
                        "type": "string",
                        "description": (
                            "Departure time, ISO local (Europe/Berlin), e.g. "
                            "'2026-04-28T06:30:00+02:00' or '2026-04-28T06:30:00'."
                        ),
                    },
                    "target_soc_pct": {
                        "type": "integer",
                        "description": "Target SoC % (10–100, typically 80).",
                        "minimum": 10,
                        "maximum": 100,
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this override is being applied (optional).",
                        "default": "user said so",
                    },
                },
                "required": ["deadline_local", "target_soc_pct"],
            },
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


class EVTools:
    """Handlers for EV charging and forecast tools."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        nats: Any,
        settings: OrchestratorSettings,
        memory: Memory,
        ev_state: dict[str, Any] | None = None,
        knowledge: KnowledgeStore | None = None,
        activity_tracker: Any = None,
    ) -> None:
        self.ha = ha
        self.nats = nats
        self.settings = settings
        self.memory = memory
        self._ev_state = ev_state or {}
        self._knowledge = knowledge
        self._activity_tracker = activity_tracker
        self._tz = ZoneInfo(settings.timezone)

    async def _read_float(self, entity_id: str, default: float = 0.0) -> float:
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", str(default))
            if val in ("unavailable", "unknown"):
                return default
            return float(val)
        except Exception:
            return default

    async def get_ev_charging_status(self) -> dict[str, Any]:
        import asyncio

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

    async def set_ev_charge_mode(self, mode: str) -> dict[str, Any]:
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

    async def set_ev_ready_by(
        self,
        deadline_local: str,
        target_soc_pct: int,
        reason: str = "user said so",
    ) -> dict[str, Any]:
        """S4.1: Publish energy.ev.command.set_ready_by for ev-forecast to apply.

        ev-forecast subscribes, sets the HA Ready-By helpers, journals the
        override, replans, and acks via energy.ev.command.acknowledged. The
        orchestrator's main.py forwards the ack to Telegram.
        """
        import uuid
        from datetime import datetime as _dt

        trace_id = uuid.uuid4().hex[:12]
        payload = {
            "deadline_local": deadline_local,
            "target_soc_pct": int(target_soc_pct),
            "reason": reason,
            "trace_id": trace_id,
            "issued_at": _dt.now(self._tz).isoformat(),
        }
        try:
            await self.nats.publish("energy.ev.command.set_ready_by", payload)
        except Exception:
            logger.exception("set_ev_ready_by_publish_failed", trace_id=trace_id)
            return {
                "success": False,
                "error": "NATS publish failed",
                "trace_id": trace_id,
            }

        decision_text = f"EV Ready-By override → {deadline_local} @ {target_soc_pct}%"
        self.memory.log_decision(
            context="EV Ready-By override",
            decision=decision_text,
            reasoning=f"{reason} (trace_id={trace_id})",
        )
        if self._activity_tracker:
            self._activity_tracker.record_decision(decision_text)

        return {
            "status": "issued",
            "trace_id": trace_id,
            "deadline_local": deadline_local,
            "target_soc_pct": int(target_soc_pct),
            "reason": reason,
            "note": (
                "Override published to ev-forecast. The plan summary will be "
                "forwarded to Telegram once ev-forecast acknowledges via "
                "energy.ev.command.acknowledged."
            ),
        }

    async def get_ev_forecast_plan(self) -> dict[str, Any]:
        plan = self._ev_state.get("plan")
        if not plan:
            return {
                "error": (
                    "No EV forecast plan available. "
                    "The ev-forecast service may not be running."
                ),
            }
        return plan

    async def respond_to_ev_trip_clarification(
        self,
        event_id: str,
        use_ev: bool,
        distance_km: float = 0,
    ) -> dict[str, Any]:
        await self.nats.publish(
            "energy.ev.forecast.trip_response",
            {
                "event_id": event_id,
                "use_ev": use_ev,
                "distance_km": distance_km,
            },
        )

        pending = self._ev_state.get("pending_clarifications", [])
        clarification = next(
            (c for c in pending if c.get("event_id") == event_id),
            {},
        )
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

        if self._knowledge and destination != "?":
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

    async def request_service_refresh(
        self,
        service: str,
        command: str = "refresh",
    ) -> dict[str, Any]:
        await self.nats.publish(f"orchestrator.command.{service}", {"command": command})
        logger.info("service_command_sent", service=service, command=command)
        return {
            "success": True,
            "service": service,
            "command": command,
            "note": f"Command '{command}' sent to {service}. The service will process it asynchronously.",
        }
