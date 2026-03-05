"""Prometheus metrics and simple HTML dashboard."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

if TYPE_CHECKING:
    from .node_manager import NodeManager

router = APIRouter()

# --- Prometheus metrics ---

REQUEST_COUNT = Counter(
    "ollama_router_requests_total", "Total requests",
    ["model", "task_type", "node", "status"],
)
REQUEST_DURATION = Histogram(
    "ollama_router_request_duration_seconds", "Request duration",
    ["model", "node"],
)
TOKENS_PER_SEC = Histogram(
    "ollama_router_tokens_per_second", "Tokens/sec",
    ["model", "node"],
)
TTFT = Histogram(
    "ollama_router_ttft_seconds", "Time to first token",
    ["model", "node"],
)
NODE_MEMORY = Gauge(
    "ollama_router_node_memory_bytes", "Node memory usage",
    ["node", "type"],
)
MODELS_LOADED = Gauge(
    "ollama_router_models_loaded", "Models loaded per node",
    ["node"],
)
QUEUE_DEPTH = Gauge(
    "ollama_router_queue_depth", "In-flight requests",
    ["node"],
)


@dataclass
class RequestRecord:
    timestamp: float
    model: str
    task_type: str
    node: str
    duration_s: float
    tokens_per_sec: float
    status: str


# Recent request log for dashboard
recent_requests: deque[RequestRecord] = deque(maxlen=100)


def record_request(
    model: str, task_type: str, node: str, duration_s: float,
    tokens_per_sec: float = 0.0, ttft_s: float = 0.0, status: str = "ok",
):
    REQUEST_COUNT.labels(model=model, task_type=task_type, node=node, status=status).inc()
    REQUEST_DURATION.labels(model=model, node=node).observe(duration_s)
    if tokens_per_sec > 0:
        TOKENS_PER_SEC.labels(model=model, node=node).observe(tokens_per_sec)
    if ttft_s > 0:
        TTFT.labels(model=model, node=node).observe(ttft_s)
    recent_requests.append(RequestRecord(
        timestamp=time.time(), model=model, task_type=task_type,
        node=node, duration_s=duration_s, tokens_per_sec=tokens_per_sec,
        status=status,
    ))


@router.get("/metrics")
async def prometheus_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    from .main import app_state
    nm = app_state.get("node_manager")
    nodes_html = ""
    if nm:
        for ns in nm.nodes.values():
            status_color = {"online": "#4caf50", "degraded": "#ff9800", "offline": "#f44336"}.get(ns.status, "#999")
            loaded = ", ".join(ns.loaded_models) or "none"
            nodes_html += f"""
            <div class="card">
                <h3><span style="color:{status_color}">●</span> {ns.name}</h3>
                <p><b>Status:</b> {ns.status} | <b>In-flight:</b> {ns.in_flight}</p>
                <p><b>Memory:</b> {ns.free_memory // (1024**2)}MB free / {ns.total_memory // (1024**2)}MB total</p>
                <p><b>Loaded:</b> {loaded}</p>
                <p><b>Available:</b> {len(ns.available_models)} models</p>
                <p><b>Latency:</b> {ns.avg_latency_ms:.0f}ms</p>
            </div>"""

    rows = ""
    for r in reversed(list(recent_requests)[-50:]):
        t = time.strftime("%H:%M:%S", time.localtime(r.timestamp))
        rows += f"<tr><td>{t}</td><td>{r.model}</td><td>{r.task_type}</td><td>{r.node}</td><td>{r.duration_s:.2f}s</td><td>{r.tokens_per_sec:.1f}</td><td>{r.status}</td></tr>"

    return f"""<!DOCTYPE html>
<html><head><title>Ollama Router Dashboard</title>
<meta http-equiv="refresh" content="10">
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; }}
.cards {{ display: flex; gap: 16px; flex-wrap: wrap; }}
.card {{ background: #16213e; border-radius: 8px; padding: 16px; min-width: 280px; }}
.card h3 {{ margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #333; }}
th {{ background: #0f3460; }}
</style></head><body>
<h1>🔀 Ollama Router</h1>
<h2>Nodes</h2>
<div class="cards">{nodes_html or "<p>No nodes configured</p>"}</div>
<h2>Recent Requests</h2>
<table><tr><th>Time</th><th>Model</th><th>Task</th><th>Node</th><th>Duration</th><th>tok/s</th><th>Status</th></tr>
{rows or "<tr><td colspan=7>No requests yet</td></tr>"}
</table></body></html>"""
