"""Health check implementations.

Each check returns a CheckResult with ok/fail status and detail text.
The Docker checker uses the Docker Engine API via Unix socket.
The diagnostic runner uses docker exec to run diagnose.py inside containers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("checks")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "warning"  # "critical" or "warning"


@dataclass
class ContainerHealth:
    service: str
    container_id: str
    status: str  # "running", "exited", "restarting", etc.
    health: str  # "healthy", "unhealthy", "starting", "none"
    restart_count: int = 0
    started_at: str = ""


@dataclass
class DiagnosticResult:
    service: str
    exit_code: int
    output: str
    passed: int = 0
    failed: int = 0
    warnings: int = 0


# ──────────────────────────────────────────────────────────────
# Infrastructure checks
# ──────────────────────────────────────────────────────────────


async def check_home_assistant(ha_url: str, ha_token: str) -> CheckResult:
    """Check if Home Assistant API is reachable."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ha_url}/api/",
                headers={"Authorization": f"Bearer {ha_token}"},
            )
            if resp.status_code == 200:
                return CheckResult("Home Assistant", True, f"API OK ({ha_url})")
            return CheckResult(
                "Home Assistant", False,
                f"HTTP {resp.status_code} from {ha_url}",
                severity="critical",
            )
    except Exception as e:
        return CheckResult("Home Assistant", False, str(e), severity="critical")


async def check_influxdb(influx_url: str, influx_token: str) -> CheckResult:
    """Check if InfluxDB is reachable."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{influx_url}/health",
                headers={"Authorization": f"Token {influx_token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")
                return CheckResult("InfluxDB", status == "pass", f"Status: {status}")
            return CheckResult("InfluxDB", False, f"HTTP {resp.status_code}")
    except Exception as e:
        return CheckResult("InfluxDB", False, str(e))


async def check_ha_entities(
    ha_url: str,
    ha_token: str,
    entity_ids: list[str],
) -> list[CheckResult]:
    """Check if key HA entities are available (not unavailable/unknown)."""
    results: list[CheckResult] = []
    headers = {"Authorization": f"Bearer {ha_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for entity_id in entity_ids:
            try:
                resp = await client.get(
                    f"{ha_url}/api/states/{entity_id}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    state = resp.json().get("state", "unknown")
                    ok = state not in ("unavailable", "unknown")
                    results.append(CheckResult(
                        f"Entity {entity_id}", ok,
                        f"State: {state}" if ok else f"State is '{state}'",
                    ))
                else:
                    results.append(CheckResult(
                        f"Entity {entity_id}", False,
                        f"HTTP {resp.status_code}",
                    ))
            except Exception as e:
                results.append(CheckResult(
                    f"Entity {entity_id}", False, str(e),
                ))

    return results


# ──────────────────────────────────────────────────────────────
# Docker checks (via Engine API over Unix socket)
# ──────────────────────────────────────────────────────────────


class DockerChecker:
    """Check container status via the Docker Engine API Unix socket."""

    def __init__(self, socket_path: str = "/var/run/docker.sock") -> None:
        self._socket = socket_path
        self._base = "http://docker"  # Arbitrary host; transport uses socket

    def _client(self) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(uds=self._socket)
        return httpx.AsyncClient(transport=transport, base_url=self._base, timeout=15.0)

    @property
    def available(self) -> bool:
        """Check if Docker socket is accessible."""
        import os
        return os.path.exists(self._socket)

    async def get_container_health(
        self,
        service_names: list[str],
    ) -> list[ContainerHealth]:
        """Get health status for each service's container."""
        results: list[ContainerHealth] = []

        if not self.available:
            logger.warning("docker_socket_not_available", path=self._socket)
            return results

        async with self._client() as client:
            try:
                resp = await client.get("/containers/json?all=true")
                if resp.status_code != 200:
                    logger.error("docker_api_error", status=resp.status_code)
                    return results

                containers = resp.json()
            except Exception:
                logger.exception("docker_api_failed")
                return results

            for container in containers:
                # Match by compose service name label
                labels = container.get("Labels", {})
                svc_name = labels.get("com.docker.compose.service", "")
                if svc_name not in service_names:
                    continue

                state = container.get("State", "unknown")
                health = "none"
                status_str = container.get("Status", "")

                # Parse health from Status string (e.g., "Up 2 hours (healthy)")
                if "(healthy)" in status_str:
                    health = "healthy"
                elif "(unhealthy)" in status_str:
                    health = "unhealthy"
                elif "(health: starting)" in status_str:
                    health = "starting"

                # Get restart count from detail endpoint
                restart_count = 0
                cid = container.get("Id", "")[:12]
                try:
                    detail_resp = await client.get(f"/containers/{cid}/json")
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        restart_count = detail.get("RestartCount", 0)
                        health_obj = detail.get("State", {}).get("Health", {})
                        if health_obj:
                            health = health_obj.get("Status", health)
                except Exception:
                    pass

                results.append(ContainerHealth(
                    service=svc_name,
                    container_id=cid,
                    status=state,
                    health=health,
                    restart_count=restart_count,
                ))

        return results

    async def run_diagnostic(self, service_name: str) -> DiagnosticResult | None:
        """Run diagnose.py inside a running container via docker exec."""
        if not self.available:
            return None

        container_id = await self._find_running_container(service_name)
        if not container_id:
            return DiagnosticResult(
                service=service_name,
                exit_code=-1,
                output=f"No running container found for {service_name}",
            )

        async with self._client() as client:
            # Step 1: Create exec instance
            try:
                resp = await client.post(
                    f"/containers/{container_id}/exec",
                    json={
                        "Cmd": ["python", "diagnose.py", "--step", "all"],
                        "AttachStdout": True,
                        "AttachStderr": True,
                    },
                )
                if resp.status_code != 201:
                    return DiagnosticResult(
                        service=service_name,
                        exit_code=-1,
                        output=f"Exec create failed: HTTP {resp.status_code}",
                    )
                exec_id = resp.json()["Id"]
            except Exception as e:
                return DiagnosticResult(
                    service=service_name,
                    exit_code=-1,
                    output=f"Exec create error: {e}",
                )

            # Step 2: Start exec and capture output
            try:
                resp = await client.post(
                    f"/exec/{exec_id}/start",
                    json={"Detach": False},
                    timeout=120.0,  # diagnose can take a while
                )
                raw_output = resp.content.decode(errors="replace")
                # Docker exec multiplexes stdout/stderr with 8-byte headers;
                # strip non-printable header bytes for readability
                output = _strip_docker_stream_headers(raw_output)
            except Exception as e:
                return DiagnosticResult(
                    service=service_name,
                    exit_code=-1,
                    output=f"Exec start error: {e}",
                )

            # Step 3: Get exit code
            exit_code = -1
            try:
                resp = await client.get(f"/exec/{exec_id}/json")
                if resp.status_code == 200:
                    exit_code = resp.json().get("ExitCode", -1)
            except Exception:
                pass

            # Count PASS/FAIL/WARN from output
            passed = output.count(" PASS ")
            failed = output.count(" FAIL ")
            warnings = output.count(" WARN ")

            return DiagnosticResult(
                service=service_name,
                exit_code=exit_code,
                output=output,
                passed=passed,
                failed=failed,
                warnings=warnings,
            )

    async def _find_running_container(self, service_name: str) -> str | None:
        """Find a running container for the given compose service name."""
        async with self._client() as client:
            try:
                resp = await client.get(
                    "/containers/json",
                    params={"filters": json.dumps({
                        "label": [f"com.docker.compose.service={service_name}"],
                        "status": ["running"],
                    })},
                )
                if resp.status_code == 200:
                    containers = resp.json()
                    if containers:
                        return containers[0]["Id"][:12]
            except Exception:
                logger.exception("docker_find_container_failed", service=service_name)

        return None


def _strip_docker_stream_headers(raw: str) -> str:
    """Strip Docker stream multiplexing headers from exec output.

    Docker multiplexed streams have 8-byte headers before each frame.
    We do a best-effort cleanup for readable text output.
    """
    # Remove non-printable characters but keep newlines, tabs, and normal ASCII
    cleaned = re.sub(r'[^\x09\x0a\x0d\x20-\x7e\x80-\xff]', '', raw)
    # Collapse multiple blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()
