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


@router.get("/api/dashboard")
async def dashboard_data():
    """JSON API for dashboard real-time updates."""
    from .main import app_state
    nm = app_state.get("node_manager")
    
    nodes_list = []
    if nm:
        for ns in nm.nodes.values():
            nodes_list.append({
                "name": ns.name,
                "url": ns.url,
                "status": ns.status.value,
                "in_flight": ns.in_flight,
                "loaded_models": ns.loaded_models,
                "available_models": ns.available_models,
                "total_memory": ns.total_memory,
                "free_memory": ns.free_memory,
                "avg_latency_ms": ns.avg_latency_ms,
                "error_count": ns.error_count,
            })
    
    requests_list = []
    for r in reversed(list(recent_requests)[-50:]):
        requests_list.append({
            "timestamp": r.timestamp,
            "model": r.model,
            "task_type": r.task_type,
            "node": r.node,
            "duration_s": r.duration_s,
            "tokens_per_sec": r.tokens_per_sec,
            "status": r.status,
        })
    
    return {
        "timestamp": time.time(),
        "nodes": nodes_list,
        "requests": requests_list,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Real-time metrics dashboard with JS auto-refresh (10s)."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Ollama Router Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            padding: 24px;
            min-height: 100vh;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            border-bottom: 2px solid #0f3460;
            padding-bottom: 16px;
        }
        .header h1 {
            font-size: 28px;
            color: #e94560;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .refresh-badge {
            display: inline-block;
            background: #4caf50;
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .refresh-badge.updating {
            animation: pulse 1s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .section {
            margin-bottom: 32px;
        }
        .section h2 {
            font-size: 18px;
            color: #e94560;
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }
        .nodes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 16px;
        }
        .node-card {
            background: rgba(15, 52, 96, 0.6);
            border: 1px solid #0f3460;
            border-radius: 8px;
            padding: 16px;
            transition: all 0.3s ease;
        }
        .node-card:hover {
            border-color: #e94560;
            box-shadow: 0 4px 12px rgba(233, 69, 96, 0.2);
        }
        .node-card h3 {
            font-size: 16px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-dot.online {
            background: #4caf50;
            animation: blink-online 2s infinite;
        }
        .status-dot.degraded {
            background: #ff9800;
            animation: blink-degraded 1s infinite;
        }
        .status-dot.offline {
            background: #f44336;
        }
        @keyframes blink-online {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        @keyframes blink-degraded {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .node-stat {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 13px;
            border-bottom: 1px solid rgba(15, 52, 96, 0.3);
        }
        .node-stat:last-child {
            border-bottom: none;
        }
        .node-stat label {
            color: #aaa;
            font-weight: 500;
        }
        .node-stat value {
            color: #fff;
            font-family: 'Monaco', 'Menlo', monospace;
            font-weight: 600;
        }
        .models-list {
            margin-top: 8px;
            padding: 8px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 4px;
            max-height: 100px;
            overflow-y: auto;
            font-size: 12px;
        }
        .model-tag {
            display: inline-block;
            background: #e94560;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            margin: 2px 2px 2px 0;
            font-weight: 500;
        }
        .no-models {
            color: #999;
            font-style: italic;
        }
        .requests-table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(15, 52, 96, 0.4);
            border: 1px solid #0f3460;
            border-radius: 6px;
            overflow: hidden;
        }
        .requests-table thead {
            background: #0f3460;
            border-bottom: 2px solid #e94560;
        }
        .requests-table th {
            padding: 12px;
            text-align: left;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .requests-table td {
            padding: 10px 12px;
            border-bottom: 1px solid rgba(15, 52, 96, 0.3);
            font-size: 13px;
        }
        .requests-table tbody tr:hover {
            background: rgba(233, 69, 96, 0.1);
        }
        .requests-table tbody tr:last-child td {
            border-bottom: none;
        }
        .status-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-badge.ok {
            background: #4caf50;
            color: white;
        }
        .status-badge.error {
            background: #f44336;
            color: white;
        }
        .empty-state {
            text-align: center;
            padding: 32px;
            color: #999;
        }
        .empty-state p {
            font-size: 14px;
        }
        .last-updated {
            font-size: 11px;
            color: #999;
            margin-top: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔀 Ollama Router</h1>
            <div class="refresh-badge" id="refreshBadge">Live</div>
        </div>

        <div class="section">
            <h2>Connected Nodes</h2>
            <div class="nodes-grid" id="nodesContainer">
                <div class="empty-state">
                    <p>Loading node status...</p>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Recent Requests</h2>
            <table class="requests-table">
                <thead>
                    <tr>
                        <th style="width: 70px;">Time</th>
                        <th style="width: 100px;">Model</th>
                        <th style="width: 80px;">Task Type</th>
                        <th style="width: 100px;">Node</th>
                        <th style="width: 80px;">Duration</th>
                        <th style="width: 80px;">Throughput</th>
                        <th style="width: 60px;">Status</th>
                    </tr>
                </thead>
                <tbody id="requestsBody">
                    <tr><td colspan="7" class="empty-state"><p>No requests yet</p></td></tr>
                </tbody>
            </table>
            <div class="last-updated" id="lastUpdated"></div>
        </div>
    </div>

    <script>
        const REFRESH_INTERVAL = 10000; // 10 seconds

        async function fetchDashboardState() {
            try {
                const response = await fetch('/api/dashboard');
                if (!response.ok) throw new Error('Failed to fetch dashboard data');
                return await response.json();
            } catch (error) {
                console.error('Error fetching dashboard state:', error);
                return null;
            }
        }

        function renderNodes(data) {
            const container = document.getElementById('nodesContainer');
            if (!data || !data.nodes || data.nodes.length === 0) {
                container.innerHTML = '<div class="empty-state"><p>No nodes configured</p></div>';
                return;
            }

            let html = '';
            data.nodes.forEach(node => {
                const statusClass = node.status || 'offline';
                const loadedModels = (node.loaded_models || []).length;
                const availableModels = (node.available_models || []).length;

                html += `
                    <div class="node-card">
                        <h3>
                            <span class="status-dot ${statusClass}"></span>
                            ${node.name}
                        </h3>
                        <div class="node-stat">
                            <label>Status</label>
                            <value>${statusClass.toUpperCase()}</value>
                        </div>
                        <div class="node-stat">
                            <label>In-Flight Requests</label>
                            <value>${node.in_flight || 0}</value>
                        </div>
                        <div class="node-stat">
                            <label>Latency</label>
                            <value>${(node.avg_latency_ms || 0).toFixed(0)}ms</value>
                        </div>
                        <div class="node-stat">
                            <label>Models</label>
                            <value>${loadedModels} loaded / ${availableModels} available</value>
                        </div>
                        <div class="models-list">
                            ${(node.loaded_models && node.loaded_models.length > 0)
                                ? node.loaded_models.map(m => `<span class="model-tag">${m}</span>`).join('')
                                : '<span class="no-models">None loaded</span>'
                            }
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function renderRequests(data) {
            const tbody = document.getElementById('requestsBody');
            if (!data || !data.requests || data.requests.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="empty-state"><p>No requests yet</p></td></tr>';
                return;
            }

            let html = '';
            const requests = (data.requests || []).slice(0, 50);
            requests.forEach(req => {
                const time = new Date(req.timestamp * 1000).toLocaleTimeString();
                const statusClass = req.status === 'ok' ? 'ok' : 'error';
                html += `
                    <tr>
                        <td>${time}</td>
                        <td><code>${req.model}</code></td>
                        <td>${req.task_type}</td>
                        <td>${req.node}</td>
                        <td>${req.duration_s.toFixed(2)}s</td>
                        <td>${req.tokens_per_sec.toFixed(1)} tok/s</td>
                        <td><span class="status-badge ${statusClass}">${req.status}</span></td>
                    </tr>
                `;
            });

            tbody.innerHTML = html || '<tr><td colspan="7"><p>No requests yet</p></td></tr>';
        }

        function updateLastUpdated() {
            const now = new Date();
            document.getElementById('lastUpdated').textContent = 
                `Last updated: ${now.toLocaleTimeString()} (auto-refresh every 10s)`;
        }

        async function refreshDashboard() {
            const badge = document.getElementById('refreshBadge');
            badge.classList.add('updating');

            const state = await fetchDashboardState();
            if (state) {
                renderNodes(state);
                renderRequests(state);
            }

            updateLastUpdated();
            badge.classList.remove('updating');
        }

        // Initial render and setup refresh timer
        refreshDashboard();
        setInterval(refreshDashboard, REFRESH_INTERVAL);
    </script>
</body>
</html>"""
