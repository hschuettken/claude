"""Diagnostic tool for health-monitor service.

Tests that the health-monitor itself can reach all the services and
infrastructure it needs to monitor.

Usage:
    docker compose run --rm health-monitor python diagnose.py
    docker compose run --rm health-monitor python diagnose.py --step mqtt
    docker compose run --rm health-monitor python diagnose.py --step ha
    docker compose run --rm health-monitor python diagnose.py --step docker
    docker compose run --rm health-monitor python diagnose.py --step telegram
    docker compose run --rm health-monitor python diagnose.py --step all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback

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
        from config import HealthMonitorSettings
        s = HealthMonitorSettings()
        result("Config loaded", True)

        checks = {
            "HA_URL": s.ha_url,
            "HA_TOKEN": s.ha_token[:8] + "..." if s.ha_token else "(empty)",
            "MQTT_HOST": s.mqtt_host,
            "INFLUXDB_URL": s.influxdb_url,
            "TELEGRAM_BOT_TOKEN": s.telegram_bot_token[:8] + "..." if s.telegram_bot_token else "(empty)",
            "TELEGRAM_ALERT_CHAT_IDS": s.telegram_alert_chat_ids or "(none)",
            "MONITORED_SERVICES": s.monitored_services,
            "HEARTBEAT_TIMEOUT_SECONDS": str(s.heartbeat_timeout_seconds),
            "INFRASTRUCTURE_CHECK_MINUTES": str(s.infrastructure_check_minutes),
            "DIAGNOSTIC_RUN_MINUTES": str(s.diagnostic_run_minutes),
            "DOCKER_SOCKET": s.docker_socket,
            "DAILY_SUMMARY_HOUR": str(s.daily_summary_hour),
            "WATCHED_ENTITIES": s.watched_entities[:80] + "..." if len(s.watched_entities) > 80 else s.watched_entities,
        }
        for key, val in checks.items():
            print(f"         {key} = {val}")

        if not s.telegram_bot_token:
            warn("TELEGRAM_BOT_TOKEN is empty — alerts will not be sent")
        if not s.telegram_alert_chat_ids:
            warn("TELEGRAM_ALERT_CHAT_IDS is empty — no recipients configured")

        return {"settings": s}

    except Exception:
        result("Config loaded", False, traceback.format_exc())
        return {}


# -- Step: Home Assistant ──────────────────────────────────────

async def check_ha(settings) -> None:
    header("Home Assistant")
    from checks import check_home_assistant

    r = await check_home_assistant(settings.ha_url, settings.ha_token)
    result("HA API", r.ok, r.detail)


# -- Step: MQTT ────────────────────────────────────────────────

def check_mqtt(settings) -> None:
    header("MQTT")
    import paho.mqtt.client as mqtt

    connected = False
    received: list[str] = []

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = (rc == 0)
        if connected:
            client.subscribe("homelab/+/heartbeat")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            svc = payload.get("service", "?")
            status = payload.get("status", "?")
            received.append(f"{svc}: {status}")
        except Exception:
            received.append(f"{msg.topic}: (parse error)")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="health-monitor-diagnose",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        time.sleep(3)
        result("Connection", connected, f"{settings.mqtt_host}:{settings.mqtt_port}")

        if connected and received:
            info(f"Service heartbeats ({len(received)}):")
            for msg in received[:10]:
                print(f"           {msg}")
        elif connected:
            info("No heartbeats received (services may not be running)")

        client.loop_stop()
        client.disconnect()
    except Exception:
        result("Connection", False, traceback.format_exc())


# -- Step: Docker ──────────────────────────────────────────────

async def check_docker(settings) -> None:
    header("Docker")
    from checks import DockerChecker

    docker = DockerChecker(settings.docker_socket)
    result("Socket exists", docker.available, settings.docker_socket)

    if not docker.available:
        warn("Docker socket not mounted — container health checks disabled")
        return

    services = [s.strip() for s in settings.monitored_services.split(",") if s.strip()]
    containers = await docker.get_container_health(services)

    if containers:
        result(f"Containers found: {len(containers)}", True)
        for c in containers:
            ok = c.health in ("healthy", "none") and c.status == "running"
            result(f"  {c.service}", ok,
                   f"Status: {c.status} | Health: {c.health} | "
                   f"Restarts: {c.restart_count}")
    else:
        warn("No matching containers found")

    # Test diagnostic execution on a running container
    if containers:
        test_svc = containers[0].service
        info(f"Testing diagnose.py exec on {test_svc}...")
        diag = await docker.run_diagnostic(test_svc)
        if diag and diag.exit_code >= 0:
            result(f"diagnose.py exec ({test_svc})", True,
                   f"Exit code: {diag.exit_code} | "
                   f"Passed: {diag.passed} | Failed: {diag.failed}")
        elif diag:
            result(f"diagnose.py exec ({test_svc})", False, diag.output[:200])
        else:
            result(f"diagnose.py exec ({test_svc})", False, "No result returned")


# -- Step: Telegram ────────────────────────────────────────────

async def check_telegram(settings) -> None:
    header("Telegram")
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
                           f"Name: {bot.get('first_name', '?')}")
                else:
                    result("Bot API", False, data.get("description", "?"))
            else:
                result("Bot API", False, f"HTTP {resp.status_code}")

        chat_ids = [c.strip() for c in settings.telegram_alert_chat_ids.split(",") if c.strip()]
        if chat_ids:
            info(f"Alert chat IDs: {chat_ids}")
        else:
            warn("No TELEGRAM_ALERT_CHAT_IDS configured")

    except Exception:
        result("Telegram", False, traceback.format_exc())


# -- Main ──────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Health Monitor diagnostic tool")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "mqtt", "docker", "telegram", "all"],
        default="all",
        help="Which check to run (default: all)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  HEALTH MONITOR — DIAGNOSTIC TOOL")
    print("=" * 60)

    ctx = check_config()
    settings = ctx.get("settings")
    if not settings:
        print("\n  Cannot proceed without valid config. Fix .env first.")
        sys.exit(1)

    if args.step in ("all", "config"):
        pass  # already ran

    if args.step in ("all", "ha"):
        await check_ha(settings)

    if args.step in ("all", "mqtt"):
        check_mqtt(settings)

    if args.step in ("all", "docker"):
        await check_docker(settings)

    if args.step in ("all", "telegram"):
        await check_telegram(settings)

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
