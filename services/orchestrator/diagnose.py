"""Diagnostic tool for orchestrator service.

Run inside the container to test connectivity and components step by step,
instead of debugging the full running service.

Usage:
    docker compose run --rm orchestrator python diagnose.py
    docker compose run --rm orchestrator python diagnose.py --step ha
    docker compose run --rm orchestrator python diagnose.py --step mqtt
    docker compose run --rm orchestrator python diagnose.py --step llm
    docker compose run --rm orchestrator python diagnose.py --step telegram
    docker compose run --rm orchestrator python diagnose.py --step calendar
    docker compose run --rm orchestrator python diagnose.py --step memory
    docker compose run --rm orchestrator python diagnose.py --step services
    docker compose run --rm orchestrator python diagnose.py --step all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback

# Bootstrap shared library
from shared.log import setup_logging

setup_logging("DEBUG")


PASS = "\033[92m PASS \033[0m"
FAIL = "\033[91m FAIL \033[0m"
WARN = "\033[93m WARN \033[0m"
INFO = "\033[94m INFO \033[0m"


def header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def result(label: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    print(f"  [{status}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def info(label: str, detail: str = "") -> None:
    print(f"  [{INFO}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def warn(label: str, detail: str = "") -> None:
    print(f"  [{WARN}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


# -- Step: Config ──────────────────────────────────────────────

def check_config() -> dict:
    header("Configuration")
    try:
        from config import OrchestratorSettings
        s = OrchestratorSettings()
        result("Config loaded", True)

        checks = {
            "HA_URL": s.ha_url,
            "HA_TOKEN": s.ha_token[:8] + "..." if s.ha_token else "(empty)",
            "MQTT_HOST": s.mqtt_host,
            "LLM_PROVIDER": s.llm_provider,
            "GEMINI_API_KEY": s.gemini_api_key[:8] + "..." if s.gemini_api_key else "(empty)",
            "TELEGRAM_BOT_TOKEN": s.telegram_bot_token[:8] + "..." if s.telegram_bot_token else "(empty)",
            "TELEGRAM_ALLOWED_CHAT_IDS": s.telegram_allowed_chat_ids or "(none)",
            "ENABLE_PROACTIVE_SUGGESTIONS": str(s.enable_proactive_suggestions),
            "ENABLE_SEMANTIC_MEMORY": str(s.enable_semantic_memory),
            "GOOGLE_CALENDAR_FAMILY_ID": s.google_calendar_family_id or "(not set)",
            "GOOGLE_CALENDAR_ORCHESTRATOR_ID": s.google_calendar_orchestrator_id or "(not set)",
            "HOUSEHOLD_USERS": s.household_users,
            "HOUSEHOLD_LANGUAGE": s.household_language,
        }
        for key, val in checks.items():
            print(f"         {key} = {val}")

        if not s.ha_token:
            warn("HA_TOKEN is empty — HA connection will fail")
        if not s.telegram_bot_token:
            warn("TELEGRAM_BOT_TOKEN is empty — Telegram will not work")
        if not s.gemini_api_key and s.llm_provider == "gemini":
            warn("GEMINI_API_KEY is empty but LLM_PROVIDER=gemini")

        return {"settings": s}

    except Exception:
        result("Config loaded", False, traceback.format_exc())
        return {}


# -- Step: Home Assistant ──────────────────────────────────────

async def check_ha(settings) -> None:
    header("Home Assistant")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        client = await ha._get_client()
        resp = await client.get("/")
        result("API reachable", resp.status_code == 200, f"Status: {resp.status_code}")

        resp = await client.get("/config")
        if resp.status_code == 200:
            config = resp.json()
            result("Config endpoint", True,
                   f"HA version: {config.get('version', '?')}\n"
                   f"Location: {config.get('latitude', '?')}, {config.get('longitude', '?')}")
        else:
            result("Config endpoint", False, f"Status: {resp.status_code}")

        # Test key energy entities
        test_entities = [
            ("Grid power", settings.grid_power_entity),
            ("PV power", settings.pv_power_entity),
            ("Battery power", settings.battery_power_entity),
            ("Battery SoC", settings.battery_soc_entity),
            ("EV power", settings.ev_power_entity),
            ("PV forecast today", settings.pv_forecast_today_entity),
            ("Charge mode", settings.ev_charge_mode_entity),
            ("Weather", settings.weather_entity),
        ]
        for label, entity_id in test_entities:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                unit = state.get("attributes", {}).get("unit_of_measurement", "")
                result(f"{label} ({entity_id})", True, f"Value: {val} {unit}")
            except Exception as e:
                result(f"{label} ({entity_id})", False, str(e))

    except Exception:
        result("API reachable", False, traceback.format_exc())
    finally:
        await ha.close()


# -- Step: MQTT ────────────────────────────────────────────────

def check_mqtt(settings) -> None:
    header("MQTT")
    import paho.mqtt.client as mqtt

    connected = False
    received_messages: list[str] = []

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = (rc == 0)
        if connected:
            client.subscribe("homelab/+/heartbeat")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            service = payload.get("service", "?")
            status = payload.get("status", "?")
            received_messages.append(f"{service}: {status}")
        except Exception:
            received_messages.append(f"{msg.topic}: (parse error)")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="orchestrator-diagnose",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        time.sleep(3)  # wait for heartbeats
        result("Connection", connected, f"{settings.mqtt_host}:{settings.mqtt_port}")

        if connected:
            pub_result = client.publish(
                "homelab/orchestrator/diagnose",
                json.dumps({"test": True}),
            )
            result("Publish test", pub_result.rc == 0, "Topic: homelab/orchestrator/diagnose")

            if received_messages:
                info(f"Service heartbeats received ({len(received_messages)}):")
                for msg in received_messages[:10]:
                    print(f"           {msg}")
            else:
                info("No service heartbeats received (other services may not be running)")

        client.loop_stop()
        client.disconnect()
    except Exception:
        result("Connection", False, traceback.format_exc())


# -- Step: LLM Provider ───────────────────────────────────────

async def check_llm(settings) -> None:
    header("LLM Provider")
    try:
        from llm import create_provider
        provider = create_provider(settings)
        result("Provider created", True, f"Type: {settings.llm_provider}")

        # Try a simple test call
        info("Testing LLM with a simple prompt...")
        from llm.base import Message
        messages = [Message(role="user", content="Reply with exactly: OK")]
        response = await provider.chat(messages, tools=None)
        text = response.content or ""
        result("LLM response", bool(text), f"Response: {text[:100]}")

    except ImportError as e:
        result("Provider import", False, str(e))
    except Exception:
        result("LLM test", False, traceback.format_exc())


# -- Step: Telegram ────────────────────────────────────────────

async def check_telegram(settings) -> None:
    header("Telegram Bot")
    if not settings.telegram_bot_token:
        warn("TELEGRAM_BOT_TOKEN not set — skipping")
        return

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot = data["result"]
                    result("Bot API", True,
                           f"Bot: @{bot.get('username', '?')}\n"
                           f"Name: {bot.get('first_name', '?')}\n"
                           f"ID: {bot.get('id', '?')}")
                else:
                    result("Bot API", False, f"API error: {data.get('description', '?')}")
            else:
                result("Bot API", False, f"HTTP {resp.status_code}")

        # Check allowed chat IDs
        chat_ids = settings.allowed_chat_ids
        if chat_ids:
            info(f"Allowed chat IDs: {chat_ids}")
        else:
            warn("No TELEGRAM_ALLOWED_CHAT_IDS configured — bot will reject all messages")

    except ImportError:
        result("httpx library", False, "pip install httpx")
    except Exception:
        result("Telegram", False, traceback.format_exc())


# -- Step: Google Calendar ─────────────────────────────────────

async def check_calendar(settings) -> None:
    header("Google Calendar")
    try:
        from gcal import GoogleCalendarClient
        gcal = GoogleCalendarClient(
            credentials_file=settings.google_calendar_credentials_file,
            credentials_json=settings.google_calendar_credentials_json,
            timezone=settings.timezone,
        )
        if not gcal.available:
            warn("Calendar not available — no credentials configured")
            return

        result("Credentials loaded", True)

        # Test family calendar
        if settings.google_calendar_family_id:
            try:
                events = await gcal.get_events(
                    calendar_id=settings.google_calendar_family_id,
                    days_ahead=3,
                    max_results=5,
                )
                result("Family calendar", True,
                       f"Calendar ID: {settings.google_calendar_family_id}\n"
                       f"Events (next 3 days): {len(events)}")
                for event in events[:3]:
                    info(f"  {event.get('summary', '?')}",
                         f"Start: {event.get('start', '?')}")
            except Exception as e:
                result("Family calendar", False, str(e))
        else:
            info("Family calendar: not configured")

        # Test orchestrator calendar
        if settings.google_calendar_orchestrator_id:
            try:
                events = await gcal.get_events(
                    calendar_id=settings.google_calendar_orchestrator_id,
                    days_ahead=3,
                    max_results=5,
                )
                result("Orchestrator calendar", True,
                       f"Calendar ID: {settings.google_calendar_orchestrator_id}\n"
                       f"Events (next 3 days): {len(events)}")
            except Exception as e:
                result("Orchestrator calendar", False, str(e))
        else:
            info("Orchestrator calendar: not configured")

    except ImportError as e:
        result("Google Calendar library", False, str(e))
    except Exception:
        result("Calendar", False, traceback.format_exc())


# -- Step: Memory ──────────────────────────────────────────────

async def check_memory(settings) -> None:
    header("Memory & Semantic Memory")

    # Regular memory
    try:
        from memory import Memory
        mem = Memory(max_history=settings.max_conversation_history)
        result("Memory system", True,
               f"Max history: {settings.max_conversation_history}")
    except Exception:
        result("Memory system", False, traceback.format_exc())

    # Semantic memory
    if not settings.enable_semantic_memory:
        info("Semantic memory: disabled (ENABLE_SEMANTIC_MEMORY=false)")
        return

    try:
        from semantic_memory import EmbeddingProvider, SemanticMemory
        embedder = EmbeddingProvider(
            provider=settings.llm_provider,
            settings=settings,
        )
        semantic = SemanticMemory(embedder)
        result("Semantic memory loaded", True,
               f"Entries: {semantic.entry_count}\n"
               f"Provider: {settings.llm_provider}")

        # Test embedding
        info("Testing embedding generation...")
        test_embedding = await embedder.embed("test diagnostic query")
        if test_embedding:
            result("Embedding API", True,
                   f"Vector dimensions: {len(test_embedding)}")
        else:
            result("Embedding API", False, "No embedding returned")

    except Exception:
        result("Semantic memory", False, traceback.format_exc())


# -- Step: Service Status ──────────────────────────────────────

def check_services(settings) -> None:
    header("Service Status (via MQTT)")
    import paho.mqtt.client as mqtt

    services: dict[str, dict] = {}

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe("homelab/+/heartbeat")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            service = payload.get("service", "unknown")
            services[service] = {
                "status": payload.get("status", "?"),
                "uptime": payload.get("uptime_seconds", 0),
                "memory_mb": payload.get("memory_mb", 0),
            }
        except Exception:
            pass

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="orchestrator-diagnose-svc",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        info("Listening for service heartbeats (5 seconds)...")
        time.sleep(5)
        client.loop_stop()
        client.disconnect()

        if services:
            result(f"Services found: {len(services)}", True)
            for svc, data in sorted(services.items()):
                status = data["status"]
                uptime_h = data["uptime"] / 3600 if data["uptime"] else 0
                mem = data["memory_mb"]
                ok = status == "online"
                result(f"  {svc}", ok,
                       f"Status: {status} | Uptime: {uptime_h:.1f}h | Memory: {mem} MB")
        else:
            warn("No services responded — other services may not be running")

    except Exception:
        result("MQTT connection", False, traceback.format_exc())


# -- Main ──────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrator diagnostic tool")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "mqtt", "llm", "telegram", "calendar", "memory", "services", "all"],
        default="all",
        help="Which check to run (default: all)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  ORCHESTRATOR — DIAGNOSTIC TOOL")
    print("=" * 60)

    ctx = check_config()
    settings = ctx.get("settings")
    if not settings:
        print("\n  Cannot proceed without valid config. Fix .env first.")
        sys.exit(1)

    if args.step in ("all", "config"):
        pass  # already ran above

    if args.step in ("all", "ha"):
        await check_ha(settings)

    if args.step in ("all", "mqtt"):
        check_mqtt(settings)

    if args.step in ("all", "llm"):
        await check_llm(settings)

    if args.step in ("all", "telegram"):
        await check_telegram(settings)

    if args.step in ("all", "calendar"):
        await check_calendar(settings)

    if args.step in ("all", "memory"):
        await check_memory(settings)

    if args.step in ("all", "services"):
        check_services(settings)

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
