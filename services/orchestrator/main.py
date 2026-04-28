"""Orchestrator service — headless home coordinator.

Headless mode: no conversational LLM loop, no Telegram channel, no proactive engine.
Service exposes MCP + REST tools and keeps HA/MQTT/Influx plumbing active.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
from shared.chroma_client import ChromaClient
from shared.service import BaseService

from api.server import create_app, start_api_server
from config import OrchestratorSettings
from gcal import GoogleCalendarClient
from knowledge import KnowledgeStore, MemoryDocument
from memory import Memory
from semantic_memory import EmbeddingProvider, SemanticMemory
from tools import ToolExecutor

import companion.db as companion_db  # noqa: F401
import companion.migrations as companion_migrations  # noqa: F401
from companion.chat import ChatEngine  # noqa: F401
from companion.cost import CostTracker  # noqa: F401
from companion.dispatch import DispatchManager  # noqa: F401
from companion.events import KairosEventPublisher  # noqa: F401
from companion.hot_state import HotStateSubscriber  # noqa: F401
from companion.memory import MemoryManager  # noqa: F401
from companion.metrics import KairosMetrics  # noqa: F401
from companion.persona import PersonaBuilder  # noqa: F401
from companion.rag import RAGEngine  # noqa: F401
from companion.router import init_router as init_companion_router  # noqa: F401
from companion.tools import ToolRegistry  # noqa: F401

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
        self._ev_events: dict[
            str, dict[str, str]
        ] = {}  # Track EV calendar events {date: {event_id, summary}}
        self._gcal: GoogleCalendarClient | None = None

    async def _register_with_oracle(self) -> None:
        """Best-effort Oracle registration. Non-critical — service must start even if Oracle is down."""
        try:
            manifest = {
                "service_name": "orchestrator",
                "port": 8050,
                "description": "AI brain — 23+ LLM-callable tools, MCP server, HA/energy/calendar control",
                "endpoints": [
                    {"method": "GET", "path": "/_health", "purpose": "Health check"},
                    {
                        "method": "GET",
                        "path": "/api/v1/status",
                        "purpose": "Service status and activity",
                    },
                    {
                        "method": "GET",
                        "path": "/api/v1/tools",
                        "purpose": "List all available tools",
                    },
                    {
                        "method": "POST",
                        "path": "/api/v1/tools/execute",
                        "purpose": "Execute a tool directly",
                    },
                    {
                        "method": "POST",
                        "path": "/api/v1/chat",
                        "purpose": "Full chat with Brain reasoning",
                    },
                    {"method": "GET", "path": "/mcp", "purpose": "MCP SSE endpoint"},
                ],
                "nats_subjects": [
                    "heartbeat.orchestrator",
                    "services.orchestrator.activity",
                    "heartbeat.>",
                    "services.*.updated",
                    "energy.ev.forecast.plan",
                    "energy.ev.forecast.clarification_needed",
                    # S3b: Energy Allocator (advisory PV-surplus arbitration)
                    "energy.demand.ev",  # subscribe — EV demand publisher
                    "energy.demand.heating",  # subscribe — HEMS demand publisher
                    "energy.pv.forecast.hourly",  # subscribe — PV forecast feed
                    "energy.allocation.ev",  # publish — advisory hint to EV
                    "energy.allocation.heating",  # publish — advisory hint to HEMS
                    # S4: manual override + LLM narration + nudges
                    "energy.ev.command.set_ready_by",  # publish from set_ev_ready_by tool
                    "energy.ev.command.acknowledged",  # subscribe to ev-forecast ack
                    "energy.ev.decision.plan",  # subscribe for narrator + nudges
                ],
                "source_paths": [
                    {"repo": "claude", "paths": ["services/orchestrator/"]},
                ],
            }
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
        except Exception:
            pass

    async def run(self) -> None:
        asyncio.create_task(self._register_with_oracle())
        memory = Memory(
            max_history=self.settings.max_conversation_history,
            max_decisions=self.settings.max_decisions,
        )

        knowledge: KnowledgeStore | None = None
        memory_doc: MemoryDocument | None = None
        if self.settings.enable_knowledge_store:
            knowledge = KnowledgeStore(nats=self.nats)
            memory_doc = MemoryDocument(max_size=self.settings.memory_document_max_size)

        gcal = GoogleCalendarClient(
            credentials_file=self.settings.google_calendar_credentials_file,
            credentials_json=self.settings.google_calendar_credentials_json,
            timezone=self.settings.timezone,
        )
        self._gcal = gcal if gcal.available else None

        # Load existing EV calendar events to prevent duplicates
        if self._gcal and self.settings.google_calendar_orchestrator_id:
            await self._load_existing_ev_events()

        semantic_memory: SemanticMemory | None = None
        if self.settings.enable_semantic_memory:
            try:
                chroma = ChromaClient()
                if not chroma.heartbeat():
                    raise RuntimeError("chroma_heartbeat_failed")
                embedder = EmbeddingProvider(
                    provider=self.settings.llm_provider, settings=self.settings
                )
                semantic_memory = SemanticMemory(
                    chroma=chroma,
                    embedder=embedder,
                    max_entries=self.settings.semantic_memory_max_entries,
                    text_max_len=self.settings.semantic_memory_text_max_len,
                    recency_weight=self.settings.semantic_memory_recency_weight,
                    recency_half_life_days=self.settings.semantic_memory_recency_half_life_days,
                )
                self.logger.info("semantic_memory_enabled")
            except Exception as exc:
                self.logger.warning("semantic_memory_disabled", error=str(exc))
        else:
            self.logger.info(
                "semantic_memory_disabled", reason="ENABLE_SEMANTIC_MEMORY=false"
            )

        tool_executor = ToolExecutor(
            ha=self.ha,
            influx=self.influx,
            nats=self.nats,
            memory=memory,
            settings=self.settings,
            gcal=gcal if gcal.available else None,
            semantic=semantic_memory,
            ev_state=self._ev_state,
            knowledge=knowledge,
            memory_doc=memory_doc,
        )
        tool_executor._activity_tracker = self._activity

        await self.nats.subscribe_json("heartbeat.>", self._on_service_heartbeat)
        await self.nats.subscribe_json("services.*.updated", self._on_service_update)
        await self.nats.subscribe_json("energy.ev.forecast.plan", self._on_ev_plan)
        await self.nats.subscribe_json(
            "energy.ev.forecast.clarification_needed", self._on_ev_clarification
        )
        # S4.1: receive ev-forecast's ack of a set_ev_ready_by override
        await self.nats.subscribe_json(
            "energy.ev.command.acknowledged", self._on_ev_command_ack
        )

        # --- S3b: Energy Allocator (advisory PV-surplus arbitration) ---
        from energy_allocator import EnergyAllocator  # noqa: F401  (deferred import keeps startup lazy)

        self.energy_allocator = EnergyAllocator(self.nats)
        await self.nats.subscribe_json(
            "energy.demand.ev", self.energy_allocator.on_demand_ev
        )
        await self.nats.subscribe_json(
            "energy.demand.heating", self.energy_allocator.on_demand_heating
        )
        await self.nats.subscribe_json(
            "energy.pv.forecast.hourly",
            self.energy_allocator.on_pv_forecast_hourly,
        )
        self.logger.info("energy_allocator_wired")

        # --- S4.3 + S4.4: EV narrator + proactive nudges ---
        try:
            import redis.asyncio as aioredis  # noqa: F401  (deferred import keeps startup lazy)

            from ev_narrator import EVNarrator  # noqa: F401  (used immediately below)
            from ev_nudges import EVNudges  # noqa: F401

            ev_redis = aioredis.from_url(
                getattr(self.settings, "redis_url", "redis://192.168.0.78:6379/0"),
                encoding="utf-8",
                decode_responses=True,
            )
            ev_router_url = getattr(
                self.settings, "llm_router_url", "http://192.168.0.50:8070"
            )

            self.ev_narrator = EVNarrator(
                nats=self.nats,
                redis_client=ev_redis,
                llm_router_url=ev_router_url,
            )
            await self.nats.subscribe_json(
                "energy.ev.decision.plan", self.ev_narrator.on_plan_journal
            )

            self.ev_nudges = EVNudges(
                redis_client=ev_redis,
                ev_state=self._ev_state,
            )
            await self.nats.subscribe_json(
                "energy.ev.decision.plan", self.ev_nudges.on_plan_journal
            )
            await self.nats.subscribe_json(
                "energy.pv.forecast.hourly", self.ev_nudges.on_pv_hourly
            )
            self.logger.info("ev_narrator_and_nudges_wired")
        except Exception:
            self.logger.exception("ev_narrator_or_nudges_init_failed")

        # --- Companion module (Kairos) ---
        companion_pool_ready: bool = False
        companion_chat_engine: ChatEngine | None = None
        companion_dispatch: DispatchManager | None = None
        companion_memory_mgr: MemoryManager | None = None
        companion_events: KairosEventPublisher | None = None
        companion_hot: HotStateSubscriber | None = None

        try:
            companion_pool = await companion_db.get_pool(self.settings)
            await companion_migrations.run_migrations(companion_pool)
            companion_pool_ready = True
            self.logger.info("companion_db_ready")

            import os
            import redis.asyncio as aioredis

            redis_url = getattr(
                self.settings, "redis_url", "redis://192.168.0.78:6379/0"
            )
            nats_url = getattr(self.settings, "nats_url", "nats://192.168.0.50:4222")
            llm_router_url = getattr(
                self.settings, "llm_router_url", "http://192.168.0.50:8070"
            )
            oracle_url = getattr(
                self.settings, "oracle_url", "http://192.168.0.50:8225"
            )

            # Hot state subscriber
            companion_hot = HotStateSubscriber(nats_url=nats_url, redis_url=redis_url)
            try:
                await companion_hot.start()
            except Exception as exc:
                self.logger.warning("companion_hot_state_start_failed", error=str(exc))
                companion_hot = None

            # Memory manager
            companion_memory_mgr = MemoryManager(
                pool=companion_pool, redis_url=redis_url
            )
            try:
                await companion_memory_mgr.connect()
            except Exception as exc:
                self.logger.warning("companion_memory_connect_failed", error=str(exc))

            # Tool registry
            policy_path = os.path.join(
                os.path.dirname(__file__), "companion", "tools_policy.yaml"
            )
            companion_tools = ToolRegistry(
                oracle_url=oracle_url, policy_path=policy_path
            )
            try:
                await companion_tools.load()
            except Exception as exc:
                self.logger.warning("companion_tools_load_failed", error=str(exc))

            # Shared Redis client (used by RAG + cost tracker)
            companion_redis = aioredis.from_url(redis_url)

            # RAG engine
            companion_rag = RAGEngine(
                redis_client=companion_redis,
                pool=companion_pool,
                graphrag_url=getattr(
                    self.settings,
                    "graphrag_url",
                    "http://192.168.0.50:8060/api/v1/graph-rag/search",
                ),
                scout_url=getattr(
                    self.settings, "scout_url", "http://192.168.0.50:8888"
                ),
                oracle_url=oracle_url,
            )

            # Persona builder
            companion_persona = PersonaBuilder()

            # Event publisher
            companion_events = KairosEventPublisher(nats_url=nats_url)
            try:
                await companion_events.connect()
            except Exception as exc:
                self.logger.warning("companion_events_connect_failed", error=str(exc))
                companion_events = None

            # Metrics + cost tracker
            companion_metrics = KairosMetrics()
            companion_cost: CostTracker | None = None
            try:
                companion_cost = CostTracker(redis_client=companion_redis)
            except Exception as exc:
                self.logger.warning(
                    "companion_cost_tracker_init_failed", error=str(exc)
                )

            # Chat engine
            fallback_hot = HotStateSubscriber(nats_url=nats_url, redis_url=redis_url)
            companion_chat_engine = ChatEngine(
                memory=companion_memory_mgr,
                hot_state=companion_hot if companion_hot is not None else fallback_hot,
                tools=companion_tools,
                rag=companion_rag,
                persona=companion_persona,
                llm_router_url=llm_router_url,
                event_publisher=companion_events,
                metrics=companion_metrics,
                cost_tracker=companion_cost,
            )

            # Dispatch manager
            companion_dispatch = DispatchManager(pool=companion_pool)

            # Wire router dependencies
            init_companion_router(
                chat_engine=companion_chat_engine,
                dispatch_manager=companion_dispatch,
                event_publisher=companion_events,
                metrics=companion_metrics,
                cost_tracker=companion_cost,
            )
            self.logger.info("companion_router_wired")

        except Exception as exc:
            self.logger.warning("companion_init_failed", error=str(exc))

        api_task: asyncio.Task | None = None
        if self.settings.orchestrator_api_key:
            api_app = create_app(
                brain=None,
                tool_executor=tool_executor,
                activity=self._activity,
                settings=self.settings,
                service_states=self._service_states,
                start_time=time.monotonic(),
                companion_chat_engine=companion_chat_engine,
                companion_dispatch_manager=companion_dispatch,
            )
            api_task = asyncio.create_task(
                start_api_server(
                    app=api_app,
                    host=self.settings.orchestrator_api_host,
                    port=self.settings.orchestrator_api_port,
                    shutdown_event=self._shutdown_event,
                ),
            )
            self.logger.info(
                "api_server_started", port=self.settings.orchestrator_api_port
            )
        else:
            self.logger.info(
                "api_server_disabled", reason="ORCHESTRATOR_API_KEY not set"
            )

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

        # Companion shutdown
        if companion_memory_mgr is not None:
            try:
                await companion_memory_mgr.close()
            except Exception:
                pass
        if companion_hot is not None:
            try:
                await companion_hot.stop()
            except Exception:
                pass
        if companion_events is not None:
            try:
                await companion_events.close()
            except Exception:
                pass
        if companion_pool_ready:
            await companion_db.close_pool()

        self.logger.info("orchestrator_stopped")

    async def _on_service_heartbeat(self, subject: str, payload: dict) -> None:
        service = payload.get("service", "unknown")
        status = payload.get("status", "unknown")
        self._service_states[service] = {
            "status": status,
            "uptime_seconds": payload.get("uptime_seconds", 0),
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    async def _on_service_update(self, subject: str, payload: dict) -> None:
        self._touch_healthcheck()

    async def _on_ev_plan(self, subject: str, payload: dict) -> None:
        self._ev_state["plan"] = payload
        # NATS callbacks run in the asyncio event loop — can await directly.
        if self._gcal and self.settings.google_calendar_orchestrator_id:
            asyncio.create_task(self._update_ev_calendar_events(payload))

    async def _on_ev_clarification(self, subject: str, payload: dict) -> None:
        self._ev_state["pending_clarifications"] = payload.get("clarifications", [])

    async def _on_ev_command_ack(self, subject: str, payload: dict) -> None:
        """S4.1: receive ev-forecast's ack of a set_ready_by override.

        Caches the latest ack on the ev_state dict so the Brain LLM can read it
        on the next user turn ("did the override apply?"). The plan summary is
        also surfaced via Telegram when ChatBot is wired (see proactive engine).
        """
        from datetime import datetime as _dt

        try:
            self._ev_state["last_command_ack"] = {
                "trace_id": payload.get("trace_id"),
                "status": payload.get("status"),
                "plan_summary": payload.get("plan_summary", ""),
                "error": payload.get("error"),
                "received_at": _dt.now().isoformat(),
            }
            self.logger.info(
                "ev_command_acked",
                trace_id=payload.get("trace_id"),
                status=payload.get("status"),
            )
        except Exception:
            self.logger.exception("ev_command_ack_handler_failed")

    async def _load_existing_ev_events(self) -> None:
        """Load existing EV calendar events from Google Calendar.

        Populates self._ev_events dict to prevent creating duplicates on restart.
        """
        try:
            cal_id = self.settings.google_calendar_orchestrator_id
            # Get events for next 14 days
            events = await self._gcal.get_events(cal_id, days_ahead=14, max_results=50)

            for event in events:
                summary = event.get("summary", "")
                if summary.startswith("EV:"):
                    start = event.get("start", "")
                    if start:  # start is YYYY-MM-DD for all-day events
                        self._ev_events[start] = {
                            "event_id": event.get("id", ""),
                            "summary": summary,
                        }
                        self.logger.info(
                            "ev_calendar_event_loaded", date=start, summary=summary
                        )
        except Exception:
            self.logger.exception("failed_to_load_existing_ev_events")

    async def _update_ev_calendar_events(self, plan_data: dict[str, Any]) -> None:
        """Create/update calendar events for significant EV charging needs.

        Called when the ev-forecast service publishes a new plan via MQTT.
        Creates all-day events on the orchestrator calendar.
        """
        from datetime import date as date_type, timedelta

        try:
            cal_id = self.settings.google_calendar_orchestrator_id
            days = plan_data.get("days", [])
            active_dates: set[str] = set()

            for day in days:
                date_str = day.get("date", "")
                urgency = day.get("urgency", "none")
                charge_kwh = day.get("energy_to_charge_kwh", 0)

                # Only create events for days that actually need charging
                if urgency == "none" or charge_kwh <= 0:
                    continue

                active_dates.add(date_str)

                # Build summary
                trips = day.get("trips", [])
                trip_parts = [f"{t['person']} → {t['destination']}" for t in trips]
                departure = day.get("departure_time")

                summary = f"EV: {charge_kwh:.0f} kWh laden"
                if departure:
                    summary += f" bis {departure}"
                if trip_parts:
                    summary += f" ({', '.join(trip_parts)})"

                # Skip if event already exists with the same summary
                existing = self._ev_events.get(date_str, {})
                if existing.get("summary") == summary:
                    continue

                # Double-check calendar for existing events on this date (safety net)
                try:
                    cal_events = await self._gcal.get_events(
                        cal_id, days_ahead=14, max_results=50
                    )
                    for evt in cal_events:
                        if (
                            evt.get("start") == date_str
                            and evt.get("summary") == summary
                        ):
                            # Found duplicate in calendar - update our dict and skip
                            self._ev_events[date_str] = {
                                "event_id": evt.get("id", ""),
                                "summary": summary,
                            }
                            self.logger.info(
                                "ev_calendar_event_exists_skipped",
                                date=date_str,
                                summary=summary,
                            )
                            existing = self._ev_events[date_str]
                            break
                    if existing.get("summary") == summary:
                        continue
                except Exception:
                    self.logger.debug("ev_calendar_query_failed", date=date_str)

                # Delete old event if exists (plan changed)
                if existing.get("event_id"):
                    try:
                        await self._gcal.delete_event(cal_id, existing["event_id"])
                    except Exception:
                        pass

                # Create new all-day event
                try:
                    d = date_type.fromisoformat(date_str)
                    next_day = (d + timedelta(days=1)).isoformat()

                    description = (
                        f"Lademodus: {day.get('charge_mode', '?')}\n"
                        f"Dringlichkeit: {urgency}\n"
                        f"Energiebedarf Fahrten: {day.get('energy_needed_kwh', 0):.1f} kWh\n"
                        f"Zu laden: {charge_kwh:.1f} kWh\n"
                        f"Grund: {day.get('reason', '')}\n\n"
                        f"Automatisch erstellt vom EV Forecast Service."
                    )

                    event = await self._gcal.create_event(
                        calendar_id=cal_id,
                        summary=summary,
                        start=date_str,
                        end=next_day,
                        description=description,
                        all_day=True,
                    )
                    self._ev_events[date_str] = {
                        "event_id": event.get("id", ""),
                        "summary": summary,
                    }
                    self.logger.info(
                        "ev_calendar_event_created", date=date_str, summary=summary
                    )
                except Exception:
                    self.logger.exception("ev_calendar_event_failed", date=date_str)

            # Clean up events for dates no longer needing charging
            for date_str in list(self._ev_events):
                if date_str not in active_dates:
                    existing = self._ev_events.pop(date_str, {})
                    if existing.get("event_id"):
                        try:
                            await self._gcal.delete_event(cal_id, existing["event_id"])
                            self.logger.info("ev_calendar_event_removed", date=date_str)
                        except Exception:
                            pass
        except Exception:
            self.logger.exception("ev_calendar_update_failed")

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
