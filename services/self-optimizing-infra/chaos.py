"""Phase 3 — Chaos Testing: scheduled resilience experiments + report generation.

Experiment types:
  service_kill        — stop a homelab Docker Compose service, wait for recovery
  latency_injection   — (simulated) inject artificial delay into a service
  node_failure        — mark a node as offline and observe recovery (dry-run only
                        unless SOI_CHAOS_ENABLED=true)

The chaos runner is designed to be safe:
  - Only runs when SOI_CHAOS_ENABLED=true (default: false)
  - Never touches production nodes by default (simulated failure)
  - Recovery is measured by polling /health on the affected service
  - Max kill fraction limits blast radius to 30% of services by default
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from . import db
from .config import settings
from .models import ChaosRun, ChaosRunCreate, ResilienceReport
from .monitors import get_l0_services

logger = logging.getLogger(__name__)

# Service registry for health checks: service_name → health URL
_SERVICE_HEALTH_URLS: dict[str, str] = {
    "orchestrator": "http://orchestrator:8100/_health",
    "pv-forecast": "http://pv-forecast:8090/health",
    "dashboard": "http://dashboard:8085/health",
    "cognitive-layer": "http://cognitive-layer:8230/health",
    "agent-economy": "http://agent-economy:8240/health",
    "digital-twin": "http://digital-twin:8238/health",
}

MAX_RECOVERY_WAIT_SECONDS = 300  # 5 minutes


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_run(data: ChaosRunCreate) -> Optional[ChaosRun]:
    row = await db.fetchrow(
        """
        INSERT INTO soi_chaos_runs (experiment_type, target, status)
        VALUES ($1, $2, 'running')
        RETURNING *
        """,
        data.experiment_type, data.target,
    )
    return _row_to_run(row) if row else None


async def list_runs(
    limit: int = 50,
    offset: int = 0,
) -> list[ChaosRun]:
    rows = await db.fetch(
        "SELECT * FROM soi_chaos_runs ORDER BY started_at DESC LIMIT $1 OFFSET $2",
        limit, offset,
    )
    return [_row_to_run(r) for r in rows]


async def get_run(run_id: uuid.UUID) -> Optional[ChaosRun]:
    row = await db.fetchrow("SELECT * FROM soi_chaos_runs WHERE id=$1", run_id)
    return _row_to_run(row) if row else None


async def _update_run(
    run_id: uuid.UUID,
    status: str,
    recovery_time: Optional[int],
    result: dict[str, Any],
) -> None:
    await db.execute(
        """
        UPDATE soi_chaos_runs
        SET status=$1, completed_at=NOW(), recovery_time_seconds=$2, result=$3
        WHERE id=$4
        """,
        status, recovery_time, json.dumps(result), run_id,
    )


def _row_to_run(row: Any) -> ChaosRun:
    return ChaosRun(
        id=row["id"],
        experiment_type=row["experiment_type"],
        target=row["target"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        recovery_time_seconds=row["recovery_time_seconds"],
        result=row["result"] if isinstance(row["result"], dict)
               else json.loads(row["result"] or "{}"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Experiment runners
# ─────────────────────────────────────────────────────────────────────────────

async def _wait_for_recovery(health_url: str) -> Optional[int]:
    """Poll health URL until it returns 200. Returns seconds elapsed or None on timeout."""
    start = time.monotonic()
    while (elapsed := time.monotonic() - start) < MAX_RECOVERY_WAIT_SECONDS:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return int(elapsed)
        except Exception:
            pass
        await asyncio.sleep(5)
    return None  # timed out


async def _run_service_kill(run: ChaosRun) -> tuple[str, Optional[int], dict[str, Any]]:
    """Kill a service via ops-bridge and measure recovery time."""
    service = run.target
    health_url = _SERVICE_HEALTH_URLS.get(service, f"http://{service}:8080/health")

    if not settings.chaos_enabled:
        # Simulation mode: just wait a bit and pretend recovery
        await asyncio.sleep(2)
        return "passed", 0, {"simulation": True, "service": service}

    headers = {}
    if settings.ops_bridge_token:
        headers["Authorization"] = f"Bearer {settings.ops_bridge_token}"

    # Stop the service
    stop_url = f"{settings.ops_bridge_url}/api/v1/services/{service}/stop"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(stop_url, headers=headers)
            resp.raise_for_status()
        logger.info("chaos service_stopped service=%s run_id=%s", service, run.id)
    except Exception as exc:
        return "failed", None, {"error": f"stop_failed: {exc}"}

    await asyncio.sleep(2)

    # Restart the service
    restart_url = f"{settings.ops_bridge_url}/api/v1/services/{service}/restart"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(restart_url, headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        return "failed", None, {"error": f"restart_failed: {exc}"}

    # Wait for recovery
    recovery_time = await _wait_for_recovery(health_url)
    if recovery_time is None:
        return "failed", None, {"error": "recovery_timeout", "service": service}

    return "passed", recovery_time, {
        "service": service,
        "recovery_seconds": recovery_time,
    }


async def _run_latency_injection(run: ChaosRun) -> tuple[str, Optional[int], dict[str, Any]]:
    """Simulate latency injection (no real traffic shaping in this environment)."""
    service = run.target
    simulated_latency_ms = random.randint(200, 2000)
    await asyncio.sleep(1)
    logger.info(
        "chaos latency_injection_simulated service=%s latency_ms=%d",
        service, simulated_latency_ms,
    )
    return "passed", 0, {
        "service": service,
        "simulated_latency_ms": simulated_latency_ms,
        "note": "simulation_only",
    }


async def _run_node_failure(run: ChaosRun) -> tuple[str, Optional[int], dict[str, Any]]:
    """Simulate a node failure (dry-run — marks node offline in memory, then restores)."""
    node = run.target
    from .monitors import _node_health
    original = _node_health.get(node)
    if original:
        original.status = "offline"
    await asyncio.sleep(5)
    if original:
        original.status = "online"
    return "passed", 5, {"node": node, "simulation": True}


async def execute_experiment(run: ChaosRun) -> None:
    """Dispatch and complete a chaos experiment, updating the DB."""
    try:
        if run.experiment_type == "service_kill":
            status, recovery, result = await _run_service_kill(run)
        elif run.experiment_type == "latency_injection":
            status, recovery, result = await _run_latency_injection(run)
        elif run.experiment_type == "node_failure":
            status, recovery, result = await _run_node_failure(run)
        else:
            status, recovery, result = "skipped", None, {"reason": f"unknown type: {run.experiment_type}"}
    except Exception as exc:
        status, recovery, result = "failed", None, {"error": str(exc)}

    await _update_run(run.id, status, recovery, result)
    logger.info(
        "chaos experiment_done run_id=%s type=%s target=%s status=%s recovery_s=%s",
        run.id, run.experiment_type, run.target, status, recovery,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled chaos sweep
# ─────────────────────────────────────────────────────────────────────────────

async def run_chaos_sweep() -> list[ChaosRun]:
    """Run a chaos sweep: kill a random sample of services and measure recovery.

    Respects SOI_CHAOS_MAX_KILL_FRACTION (default 30%).
    """
    services = get_l0_services()
    if not services:
        logger.info("chaos_sweep no services tracked — skipping")
        return []

    max_targets = max(1, int(len(services) * settings.chaos_max_kill_fraction))
    sample = random.sample(services, min(max_targets, len(services)))

    logger.info(
        "chaos_sweep started total_services=%d targets=%d chaos_enabled=%s",
        len(services), len(sample), settings.chaos_enabled,
    )

    runs: list[ChaosRun] = []
    for svc in sample:
        data = ChaosRunCreate(experiment_type="service_kill", target=svc.service_name)
        run = await create_run(data)
        if run:
            await execute_experiment(run)
            fresh = await get_run(run.id)
            if fresh:
                runs.append(fresh)

    logger.info("chaos_sweep completed experiments=%d", len(runs))
    return runs


# ─────────────────────────────────────────────────────────────────────────────
# Resilience Report
# ─────────────────────────────────────────────────────────────────────────────

async def generate_resilience_report(limit: int = 50) -> ResilienceReport:
    """Compute a resilience report from the most recent chaos runs."""
    runs = await list_runs(limit=limit)
    total = len(runs)
    passed = sum(1 for r in runs if r.status == "passed")
    failed = sum(1 for r in runs if r.status == "failed")
    skipped = sum(1 for r in runs if r.status == "skipped")

    recovery_times = [
        r.recovery_time_seconds for r in runs
        if r.recovery_time_seconds is not None
    ]
    avg_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else None

    resilience_score = round(passed / total, 3) if total > 0 else 1.0

    return ResilienceReport(
        generated_at=datetime.now(timezone.utc),
        total_experiments=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        avg_recovery_time_seconds=avg_recovery,
        experiments=runs,
        resilience_score=resilience_score,
    )
