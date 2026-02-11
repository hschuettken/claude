"""Health Monitor Service — watches all homelab services and infrastructure.

Monitors:
  - MQTT heartbeats from all services (detect offline/online transitions)
  - Docker container health status (healthy/unhealthy/restarting)
  - Infrastructure connectivity (HA, MQTT, InfluxDB)
  - Key HA entity availability
  - Runs diagnose.py inside service containers periodically

Alerts via Telegram with per-issue cooldown to avoid spam.
Publishes its own status to MQTT + HA auto-discovery sensors.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from shared.service import BaseService

from alerts import TelegramAlerter
from checks import (
    CheckResult,
    ContainerHealth,
    DockerChecker,
    check_ha_entities,
    check_home_assistant,
    check_influxdb,
)
from config import HealthMonitorSettings

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class HealthMonitorService(BaseService):
    name = "health-monitor"

    def __init__(self) -> None:
        self.settings = HealthMonitorSettings()
        super().__init__(settings=self.settings)

        self._tz = ZoneInfo(self.settings.timezone)

        # Parse config
        self._monitored_services = [
            s.strip() for s in self.settings.monitored_services.split(",") if s.strip()
        ]
        chat_ids = [
            int(c.strip())
            for c in self.settings.telegram_alert_chat_ids.split(",")
            if c.strip()
        ]
        watched = [
            e.strip() for e in self.settings.watched_entities.split(",") if e.strip()
        ]

        # Components
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_ids=chat_ids,
            cooldown_seconds=self.settings.alert_cooldown_minutes * 60,
        )
        self.docker = DockerChecker(self.settings.docker_socket)
        self._watched_entities = watched

        # State tracking
        self._service_states: dict[str, dict[str, Any]] = {}
        self._last_heartbeat: dict[str, float] = {}
        self._container_health: dict[str, ContainerHealth] = {}
        self._infra_status: dict[str, bool] = {}
        self._last_diagnostic: dict[str, dict[str, Any]] = {}
        self._last_summary_date: str = ""

    async def run(self) -> None:
        self.mqtt.connect_background()
        self._register_ha_discovery()

        # Subscribe to all service heartbeats
        self.mqtt.subscribe("homelab/+/heartbeat", self._on_heartbeat)

        self.logger.info(
            "health_monitor_started",
            services=self._monitored_services,
            telegram=self.alerter.available,
            docker=self.docker.available,
            watched_entities=len(self._watched_entities),
        )

        # Send startup notification
        if self.alerter.available:
            services_str = ", ".join(self._monitored_services)
            await self.alerter.send_alert(
                "__startup__",
                f"Health Monitor started.\nMonitoring: {services_str}\n"
                f"Docker: {'available' if self.docker.available else 'not available'}",
                severity="info",
            )

        self._touch_healthcheck()

        # Run all checks concurrently in background
        tasks = [
            asyncio.create_task(self._heartbeat_monitor_loop()),
            asyncio.create_task(self._infrastructure_check_loop()),
            asyncio.create_task(self._docker_check_loop()),
            asyncio.create_task(self._diagnostic_loop()),
            asyncio.create_task(self._entity_check_loop()),
            asyncio.create_task(self._daily_summary_loop()),
            asyncio.create_task(self._status_publish_loop()),
        ]

        await self.wait_for_shutdown()

        for task in tasks:
            task.cancel()

    # ------------------------------------------------------------------
    # MQTT heartbeat monitoring
    # ------------------------------------------------------------------

    def _on_heartbeat(self, topic: str, payload: dict[str, Any]) -> None:
        """Track service heartbeats."""
        service = payload.get("service", "")
        if not service:
            return

        now = time.time()
        was_offline = (
            service in self._monitored_services
            and service in self._service_states
            and self._service_states[service].get("status") == "offline"
        )

        self._service_states[service] = {
            "status": payload.get("status", "online"),
            "uptime_seconds": payload.get("uptime_seconds", 0),
            "memory_mb": payload.get("memory_mb", 0),
            "last_seen": now,
        }
        self._last_heartbeat[service] = now

        # Recovery alert if service was marked offline
        if was_offline and payload.get("status") == "online":
            asyncio.get_event_loop().create_task(
                self.alerter.send_recovery(
                    f"heartbeat:{service}",
                    f"Service *{service}* is back online.",
                )
            )

    async def _heartbeat_monitor_loop(self) -> None:
        """Periodically check for services that stopped sending heartbeats."""
        timeout = self.settings.heartbeat_timeout_seconds
        await asyncio.sleep(30)  # Grace period on startup

        while not self._shutdown_event.is_set():
            now = time.time()

            for service in self._monitored_services:
                last = self._last_heartbeat.get(service, 0)

                if last == 0:
                    # Never seen — might not be started yet
                    if service not in self._service_states:
                        self._service_states[service] = {"status": "unknown", "last_seen": 0}
                    continue

                age = now - last
                if age > timeout:
                    # Mark as offline
                    self._service_states[service]["status"] = "offline"
                    minutes = int(age / 60)
                    await self.alerter.send_alert(
                        f"heartbeat:{service}",
                        f"Service *{service}* has not sent a heartbeat "
                        f"for {minutes} minutes.",
                        severity="critical",
                    )

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Infrastructure checks
    # ------------------------------------------------------------------

    async def _infrastructure_check_loop(self) -> None:
        """Periodically check HA, InfluxDB connectivity."""
        await asyncio.sleep(10)  # Initial delay

        while not self._shutdown_event.is_set():
            # Home Assistant
            ha_result = await check_home_assistant(
                self.settings.ha_url, self.settings.ha_token,
                timeout=self.settings.http_check_timeout_seconds,
            )
            prev_ha = self._infra_status.get("ha")
            self._infra_status["ha"] = ha_result.ok

            if not ha_result.ok:
                await self.alerter.send_alert(
                    "infra:ha",
                    f"Home Assistant unreachable: {ha_result.detail}",
                    severity="critical",
                )
            elif prev_ha is False:
                await self.alerter.send_recovery(
                    "infra:ha",
                    "Home Assistant is reachable again.",
                )

            # InfluxDB
            influx_result = await check_influxdb(
                self.settings.influxdb_url, self.settings.influxdb_token,
                timeout=self.settings.http_check_timeout_seconds,
            )
            prev_influx = self._infra_status.get("influx")
            self._infra_status["influx"] = influx_result.ok

            if not influx_result.ok:
                await self.alerter.send_alert(
                    "infra:influx",
                    f"InfluxDB issue: {influx_result.detail}",
                    severity="warning",
                )
            elif prev_influx is False:
                await self.alerter.send_recovery(
                    "infra:influx",
                    "InfluxDB is healthy again.",
                )

            self._touch_healthcheck()

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.infrastructure_check_minutes * 60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Docker container health
    # ------------------------------------------------------------------

    async def _docker_check_loop(self) -> None:
        """Periodically check Docker container health status."""
        if not self.docker.available:
            self.logger.info("docker_checks_disabled", reason="socket not available")
            return

        await asyncio.sleep(15)

        while not self._shutdown_event.is_set():
            try:
                containers = await self.docker.get_container_health(
                    self._monitored_services,
                )

                for c in containers:
                    prev = self._container_health.get(c.service)
                    self._container_health[c.service] = c

                    # Alert on unhealthy
                    if c.health == "unhealthy":
                        await self.alerter.send_alert(
                            f"docker:{c.service}",
                            f"Container *{c.service}* is unhealthy.\n"
                            f"Status: {c.status} | Restarts: {c.restart_count}",
                            severity="warning",
                        )
                    elif (
                        prev
                        and prev.health == "unhealthy"
                        and c.health == "healthy"
                    ):
                        await self.alerter.send_recovery(
                            f"docker:{c.service}",
                            f"Container *{c.service}* is healthy again.",
                        )

                    # Alert on excessive restarts
                    prev_restarts = prev.restart_count if prev else 0
                    if c.restart_count > prev_restarts and c.restart_count > 2:
                        await self.alerter.send_alert(
                            f"docker_restart:{c.service}",
                            f"Container *{c.service}* has restarted "
                            f"{c.restart_count} times.",
                            severity="warning",
                        )

            except Exception:
                self.logger.exception("docker_check_error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.docker_check_minutes * 60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Diagnostic runner
    # ------------------------------------------------------------------

    async def _diagnostic_loop(self) -> None:
        """Periodically run diagnose.py inside each service container."""
        if not self.docker.available:
            self.logger.info("diagnostics_disabled", reason="docker socket not available")
            return

        # Wait for services to fully start
        await asyncio.sleep(120)

        while not self._shutdown_event.is_set():
            for service in self._monitored_services:
                try:
                    result = await self.docker.run_diagnostic(service)
                    if result is None:
                        continue

                    self._last_diagnostic[service] = {
                        "exit_code": result.exit_code,
                        "passed": result.passed,
                        "failed": result.failed,
                        "warnings": result.warnings,
                        "timestamp": datetime.now(self._tz).isoformat(),
                    }

                    self.logger.info(
                        "diagnostic_result",
                        service=service,
                        exit_code=result.exit_code,
                        passed=result.passed,
                        failed=result.failed,
                        warnings=result.warnings,
                    )

                    if result.failed > 0:
                        # Extract just the FAIL lines for the alert
                        fail_lines = [
                            line.strip()
                            for line in result.output.split("\n")
                            if "FAIL" in line
                        ]
                        fail_summary = "\n".join(fail_lines[:5]) or "See container logs"

                        await self.alerter.send_alert(
                            f"diag:{service}",
                            f"Diagnostic failed for *{service}*:\n"
                            f"{result.failed} check(s) failed\n\n"
                            f"```\n{fail_summary}\n```",
                            severity="warning",
                        )
                    elif self.alerter.active_issues.get(f"diag:{service}"):
                        await self.alerter.send_recovery(
                            f"diag:{service}",
                            f"Diagnostics for *{service}* are passing again "
                            f"({result.passed} passed).",
                        )

                except Exception:
                    self.logger.exception("diagnostic_run_error", service=service)

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.diagnostic_run_minutes * 60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Entity staleness checks
    # ------------------------------------------------------------------

    async def _entity_check_loop(self) -> None:
        """Periodically check if key HA entities have become unavailable."""
        if not self._watched_entities:
            return

        await asyncio.sleep(60)

        while not self._shutdown_event.is_set():
            try:
                results = await check_ha_entities(
                    self.settings.ha_url,
                    self.settings.ha_token,
                    self._watched_entities,
                    timeout=self.settings.http_check_timeout_seconds,
                )
                for r in results:
                    entity_key = r.name.replace("Entity ", "")
                    if not r.ok:
                        await self.alerter.send_alert(
                            f"entity:{entity_key}",
                            f"HA entity *{entity_key}* is {r.detail}",
                            severity="warning",
                        )
                    elif self.alerter.active_issues.get(f"entity:{entity_key}"):
                        await self.alerter.send_recovery(
                            f"entity:{entity_key}",
                            f"HA entity *{entity_key}* is available again: {r.detail}",
                        )
            except Exception:
                self.logger.exception("entity_check_error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.entity_check_minutes * 60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    async def _daily_summary_loop(self) -> None:
        """Send a daily health summary at the configured hour."""
        if self.settings.daily_summary_hour < 0:
            return

        while not self._shutdown_event.is_set():
            now = datetime.now(self._tz)
            today = now.strftime("%Y-%m-%d")

            if (
                now.hour == self.settings.daily_summary_hour
                and self._last_summary_date != today
            ):
                self._last_summary_date = today
                await self._send_daily_summary()
                self.alerter.reset_daily_counters()

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=60,
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _send_daily_summary(self) -> None:
        """Compose and send the daily summary."""
        lines: list[str] = []
        now = datetime.now(self._tz)
        lines.append(f"*{now.strftime('%A, %d %B %Y')}*\n")

        # Service status
        online = 0
        for svc in self._monitored_services:
            state = self._service_states.get(svc, {})
            status = state.get("status", "unknown")
            if status == "online":
                online += 1
            uptime_h = state.get("uptime_seconds", 0) / 3600
            icon = "🟢" if status == "online" else ("🔴" if status == "offline" else "⚪")
            lines.append(f"{icon} *{svc}*: {status} ({uptime_h:.1f}h)")

        lines.append(f"\nServices: {online}/{len(self._monitored_services)} online")

        # Infrastructure
        ha_ok = self._infra_status.get("ha")
        influx_ok = self._infra_status.get("influx")
        infra_items = []
        if ha_ok is not None:
            infra_items.append(f"HA: {'OK' if ha_ok else 'FAIL'}")
        if influx_ok is not None:
            infra_items.append(f"InfluxDB: {'OK' if influx_ok else 'FAIL'}")
        if infra_items:
            lines.append(f"Infrastructure: {' | '.join(infra_items)}")

        # Docker health
        if self._container_health:
            unhealthy = [
                c.service for c in self._container_health.values()
                if c.health == "unhealthy"
            ]
            if unhealthy:
                lines.append(f"Unhealthy containers: {', '.join(unhealthy)}")
            else:
                lines.append("All containers healthy")

        # Diagnostics
        if self._last_diagnostic:
            diag_issues = [
                f"{svc} ({d['failed']} failed)"
                for svc, d in self._last_diagnostic.items()
                if d.get("failed", 0) > 0
            ]
            if diag_issues:
                lines.append(f"Diagnostic issues: {', '.join(diag_issues)}")
            else:
                lines.append("All diagnostics passing")

        # Active issues
        active = self.alerter.active_issues
        if active:
            lines.append(f"\nActive issues ({len(active)}):")
            for key, msg in list(active.items())[:5]:
                lines.append(f"  - {msg[:80]}")

        # Alert stats
        stats = self.alerter.get_stats()
        lines.append(
            f"\nAlerts: {stats['alerts_sent_today']} sent, "
            f"{stats['recoveries_sent_today']} recoveries"
        )

        await self.alerter.send_summary("\n".join(lines))

    # ------------------------------------------------------------------
    # Status publishing
    # ------------------------------------------------------------------

    async def _status_publish_loop(self) -> None:
        """Publish health monitor status to MQTT periodically."""
        await asyncio.sleep(10)

        while not self._shutdown_event.is_set():
            online = sum(
                1 for s in self._monitored_services
                if self._service_states.get(s, {}).get("status") == "online"
            )

            self.publish("status", {
                "services_monitored": len(self._monitored_services),
                "services_online": online,
                "active_issues": self.alerter.active_issue_count,
                "ha_ok": self._infra_status.get("ha", False),
                "influx_ok": self._infra_status.get("influx", False),
                "docker_available": self.docker.available,
                "telegram_available": self.alerter.available,
                "last_check": datetime.now(self._tz).isoformat(),
            })

            self._touch_healthcheck()

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=60,
                )
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # HA MQTT auto-discovery
    # ------------------------------------------------------------------

    def _register_ha_discovery(self) -> None:
        device = {
            "identifiers": ["homelab_health_monitor"],
            "name": "Health Monitor",
            "manufacturer": "Homelab",
            "model": "health-monitor",
        }
        node = "health_monitor"
        status_topic = "homelab/health-monitor/status"
        heartbeat_topic = "homelab/health-monitor/heartbeat"

        self.mqtt.publish_ha_discovery("binary_sensor", "service_status", node_id=node, config={
            "name": "Health Monitor Status",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
            "expire_after": 180,
            "icon": "mdi:heart-pulse",
        })

        self.mqtt.publish_ha_discovery("sensor", "services_online", node_id=node, config={
            "name": "Services Online",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ value_json.services_online }}",
            "icon": "mdi:server-network",
        })

        self.mqtt.publish_ha_discovery("sensor", "services_monitored", node_id=node, config={
            "name": "Services Monitored",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ value_json.services_monitored }}",
            "icon": "mdi:server-network",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "active_issues", node_id=node, config={
            "name": "Active Issues",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ value_json.active_issues }}",
            "icon": "mdi:alert-circle-outline",
        })

        self.mqtt.publish_ha_discovery("binary_sensor", "ha_ok", node_id=node, config={
            "name": "Home Assistant Connectivity",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ 'ON' if value_json.ha_ok else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
            "icon": "mdi:home-assistant",
        })

        self.mqtt.publish_ha_discovery("binary_sensor", "influx_ok", node_id=node, config={
            "name": "InfluxDB Connectivity",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ 'ON' if value_json.influx_ok else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
            "icon": "mdi:database",
        })

        self.mqtt.publish_ha_discovery("sensor", "uptime", node_id=node, config={
            "name": "Health Monitor Uptime",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ value_json.uptime_seconds | round(0) }}",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "entity_category": "diagnostic",
            "icon": "mdi:timer-outline",
        })

        self.mqtt.publish_ha_discovery("sensor", "last_check", node_id=node, config={
            "name": "Last Health Check",
            "device": device,
            "state_topic": status_topic,
            "value_template": "{{ value_json.last_check }}",
            "device_class": "timestamp",
            "icon": "mdi:clock-check-outline",
            "entity_category": "diagnostic",
        })

        self.logger.info("ha_discovery_registered", entity_count=8)

    # ------------------------------------------------------------------
    # Custom health check for BaseService heartbeat
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        online = sum(
            1 for s in self._monitored_services
            if self._service_states.get(s, {}).get("status") == "online"
        )
        return {
            "services_online": online,
            "active_issues": self.alerter.active_issue_count,
        }

    # ------------------------------------------------------------------
    # Healthcheck file
    # ------------------------------------------------------------------

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass


if __name__ == "__main__":
    service = HealthMonitorService()
    asyncio.run(service.start())
