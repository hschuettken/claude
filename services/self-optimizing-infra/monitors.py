"""L0 / L1 / L2 infrastructure monitors.

L0 — agent health: tracks homelab service heartbeats via NATS.
L1 — infra health: polls Proxmox, Bootstrap bridge, K3s for node status.
L2 — reasoning layer: aggregates L0/L1 signals for the decision engine.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .config import settings
from .models import NodeHealth, ServiceHealth

logger = logging.getLogger(__name__)

# In-memory health tables (populated by NATS callbacks / polling loops).
# The decision engine reads these directly for low-latency evaluation.
_service_health: dict[str, ServiceHealth] = {}
_node_health: dict[str, NodeHealth] = {}

# Last heartbeat timestamps (epoch seconds) — used for L0 timeout detection.
_heartbeat_ts: dict[str, float] = {}


# ─────────────────────────────────────────────────────────────────────────────
# L0 — agent health (NATS heartbeat subscriber)
# ─────────────────────────────────────────────────────────────────────────────

def on_heartbeat(service_name: str, payload: dict[str, Any]) -> None:
    """Called from the NATS heartbeat subscriber for each received heartbeat."""
    now = datetime.now(timezone.utc)
    _heartbeat_ts[service_name] = time.monotonic()
    status = payload.get("status", "online")
    _service_health[service_name] = ServiceHealth(
        service_name=service_name,
        monitor_level="L0",
        status=status,
        last_seen=now,
        metadata={
            "uptime_seconds": payload.get("uptime_seconds"),
            "memory_mb": payload.get("memory_mb"),
        },
        updated_at=now,
    )
    logger.debug("l0_heartbeat service=%s status=%s", service_name, status)


def check_stale_services() -> list[str]:
    """Return names of services whose last heartbeat exceeded the timeout."""
    now_mono = time.monotonic()
    timeout = settings.heartbeat_timeout_seconds
    stale = []
    for name, ts in _heartbeat_ts.items():
        if (now_mono - ts) > timeout:
            stale.append(name)
            svc = _service_health.get(name)
            if svc and svc.status != "offline":
                svc.status = "offline"
                svc.updated_at = datetime.now(timezone.utc)
                logger.warning("l0_service_offline service=%s", name)
    return stale


def get_l0_services() -> list[ServiceHealth]:
    return list(_service_health.values())


# ─────────────────────────────────────────────────────────────────────────────
# L1 — infra health (Bootstrap bridge, Proxmox, K3s)
# ─────────────────────────────────────────────────────────────────────────────

async def poll_bootstrap_bridge() -> list[NodeHealth]:
    """Fetch node list from the Bootstrap bridge REST API."""
    url = f"{settings.bootstrap_url}/api/v1/nodes"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("l1_bootstrap_poll_failed url=%s error=%s", url, exc)
        return []

    nodes: list[NodeHealth] = []
    items = data if isinstance(data, list) else data.get("nodes", [])
    for item in items:
        node_id = str(item.get("id") or item.get("node_id") or item.get("hostname", "unknown"))
        status_raw = str(item.get("status", "unknown")).lower()
        status = "online" if status_raw in ("online", "up", "active", "running") else "offline"
        nh = NodeHealth(
            node_id=node_id,
            node_name=item.get("name") or item.get("hostname") or node_id,
            status=status,
            cpu_percent=item.get("cpu_percent") or item.get("cpu_usage"),
            mem_percent=item.get("mem_percent") or item.get("memory_usage"),
            disk_percent=item.get("disk_percent") or item.get("disk_usage"),
            uptime_seconds=item.get("uptime_seconds"),
            source="bootstrap",
            metadata=item,
            checked_at=datetime.now(timezone.utc),
        )
        _node_health[f"bootstrap:{node_id}"] = nh
        nodes.append(nh)

    logger.debug("l1_bootstrap_polled count=%d", len(nodes))
    return nodes


async def poll_proxmox() -> list[NodeHealth]:
    """Fetch Proxmox node and VM status via the PVE REST API."""
    if not settings.proxmox_token_id or not settings.proxmox_token_secret:
        return []

    headers = {
        "Authorization": f"PVEAPIToken={settings.proxmox_token_id}={settings.proxmox_token_secret}"
    }
    nodes: list[NodeHealth] = []
    try:
        async with httpx.AsyncClient(
            timeout=10,
            verify=settings.proxmox_verify_ssl,
        ) as client:
            resp = await client.get(
                f"{settings.proxmox_url}/api2/json/nodes",
                headers=headers,
            )
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                node_id = item.get("node", "unknown")
                online = item.get("status") == "online"
                nh = NodeHealth(
                    node_id=node_id,
                    node_name=node_id,
                    status="online" if online else "offline",
                    cpu_percent=round(item.get("cpu", 0) * 100, 1),
                    mem_percent=round(
                        item.get("mem", 0) / max(item.get("maxmem", 1), 1) * 100, 1
                    ),
                    disk_percent=round(
                        item.get("disk", 0) / max(item.get("maxdisk", 1), 1) * 100, 1
                    ),
                    uptime_seconds=item.get("uptime"),
                    source="proxmox",
                    metadata=item,
                    checked_at=datetime.now(timezone.utc),
                )
                _node_health[f"proxmox:{node_id}"] = nh
                nodes.append(nh)
    except Exception as exc:
        logger.warning("l1_proxmox_poll_failed error=%s", exc)

    logger.debug("l1_proxmox_polled count=%d", len(nodes))
    return nodes


async def poll_k3s() -> list[NodeHealth]:
    """Fetch K3s node status via the Kubernetes API."""
    if not settings.k3s_token:
        return []

    headers = {"Authorization": f"Bearer {settings.k3s_token}"}
    nodes: list[NodeHealth] = []
    try:
        async with httpx.AsyncClient(
            timeout=10,
            verify=False,  # self-signed cert common in local K3s
        ) as client:
            resp = await client.get(
                f"{settings.k3s_api_url}/api/v1/nodes",
                headers=headers,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                node_name = item["metadata"]["name"]
                conditions = {
                    c["type"]: c["status"]
                    for c in item.get("status", {}).get("conditions", [])
                }
                ready = conditions.get("Ready", "False") == "True"
                alloc = item.get("status", {}).get("allocatable", {})
                nh = NodeHealth(
                    node_id=node_name,
                    node_name=node_name,
                    status="online" if ready else "offline",
                    source="k3s",
                    metadata={"conditions": conditions, "allocatable": alloc},
                    checked_at=datetime.now(timezone.utc),
                )
                _node_health[f"k3s:{node_name}"] = nh
                nodes.append(nh)
    except Exception as exc:
        logger.warning("l1_k3s_poll_failed error=%s", exc)

    logger.debug("l1_k3s_polled count=%d", len(nodes))
    return nodes


async def run_l1_poll() -> list[NodeHealth]:
    """Run all L1 polls concurrently and return combined node list."""
    results = await asyncio.gather(
        poll_bootstrap_bridge(),
        poll_proxmox(),
        poll_k3s(),
        return_exceptions=True,
    )
    nodes: list[NodeHealth] = []
    for r in results:
        if isinstance(r, list):
            nodes.extend(r)
    return nodes


def get_l1_nodes() -> list[NodeHealth]:
    return list(_node_health.values())


# ─────────────────────────────────────────────────────────────────────────────
# L2 — aggregate snapshot for the decision engine
# ─────────────────────────────────────────────────────────────────────────────

def get_infra_snapshot() -> dict[str, Any]:
    """Return a unified view of all monitored resources for the decision engine."""
    stale = check_stale_services()
    services = get_l0_services()
    nodes = get_l1_nodes()

    offline_services = [s for s in services if s.status != "online"]
    offline_nodes = [n for n in nodes if n.status != "online"]
    high_cpu_nodes = [
        n for n in nodes
        if n.cpu_percent is not None and n.cpu_percent > 85.0
    ]
    high_mem_nodes = [
        n for n in nodes
        if n.mem_percent is not None and n.mem_percent > 90.0
    ]

    return {
        "total_services": len(services),
        "offline_services": [s.service_name for s in offline_services],
        "stale_services": stale,
        "total_nodes": len(nodes),
        "offline_nodes": [n.node_name for n in offline_nodes],
        "high_cpu_nodes": [
            {"name": n.node_name, "cpu_percent": n.cpu_percent}
            for n in high_cpu_nodes
        ],
        "high_mem_nodes": [
            {"name": n.node_name, "mem_percent": n.mem_percent}
            for n in high_mem_nodes
        ],
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }
