"""Node health polling, status tracking, model inventory."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .config import Settings
from .models import NodeState, NodeStatus
from .metrics import NODE_MEMORY, MODELS_LOADED, QUEUE_DEPTH

logger = logging.getLogger("ollama-router.nodes")


class NodeManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.nodes: dict[str, NodeState] = {}
        self._client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task | None = None

        for nc in settings.nodes:
            self.nodes[nc.name] = NodeState(
                name=nc.name, url=nc.url, tags=nc.tags,
                max_concurrent=nc.max_concurrent,
            )

    async def start(self):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Node manager started, polling %d nodes", len(self.nodes))

    async def stop(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    async def _poll_loop(self):
        # Initial poll immediately
        await self._poll_all()
        interval = self.settings.lifecycle.health_check_interval
        while True:
            await asyncio.sleep(interval)
            await self._poll_all()

    async def _poll_all(self):
        tasks = [self._poll_node(ns) for ns in self.nodes.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_node(self, ns: NodeState):
        assert self._client
        try:
            start = time.monotonic()

            # Get available models
            resp_tags = await self._client.get(f"{ns.url}/api/tags")
            latency = (time.monotonic() - start) * 1000
            resp_tags.raise_for_status()
            tags_data = resp_tags.json()
            ns.available_models = [m["name"] for m in tags_data.get("models", [])]

            # Get loaded models
            resp_ps = await self._client.get(f"{ns.url}/api/ps")
            resp_ps.raise_for_status()
            ps_data = resp_ps.json()
            ps_models = ps_data.get("models", [])
            ns.loaded_models = [m["name"] for m in ps_models]

            # Extract memory info from ps response
            total_size = sum(m.get("size", 0) for m in ps_models)
            total_vram = sum(m.get("size_vram", 0) for m in ps_models)
            ns.total_memory = max(ns.total_memory, total_size + total_vram)

            # Update metrics
            ns.avg_latency_ms = latency if ns.avg_latency_ms == 0 else (ns.avg_latency_ms * 0.8 + latency * 0.2)
            ns.last_seen = time.time()
            ns.error_count = 0

            if latency > 5000:
                ns.status = NodeStatus.DEGRADED
            else:
                ns.status = NodeStatus.ONLINE

            # Prometheus gauges
            MODELS_LOADED.labels(node=ns.name).set(len(ns.loaded_models))
            QUEUE_DEPTH.labels(node=ns.name).set(ns.in_flight)
            NODE_MEMORY.labels(node=ns.name, type="used").set(total_size)

        except Exception as e:
            ns.error_count += 1
            if ns.error_count >= 3:
                ns.status = NodeStatus.OFFLINE
            else:
                ns.status = NodeStatus.DEGRADED
            logger.warning("Poll failed for %s: %s", ns.name, e)

    def get_online_nodes(self) -> list[NodeState]:
        return [ns for ns in self.nodes.values() if ns.status != NodeStatus.OFFLINE]

    def get_nodes_with_model(self, model: str, loaded_only: bool = False) -> list[NodeState]:
        """Find nodes that have (or can serve) a model."""
        result = []
        for ns in self.nodes.values():
            if ns.status == NodeStatus.OFFLINE:
                continue
            if loaded_only:
                if model in ns.loaded_models:
                    result.append(ns)
            else:
                if model in ns.available_models or model in ns.loaded_models:
                    result.append(ns)
        return result

    def increment_in_flight(self, node_name: str):
        if node_name in self.nodes:
            self.nodes[node_name].in_flight += 1
            QUEUE_DEPTH.labels(node=node_name).set(self.nodes[node_name].in_flight)

    def decrement_in_flight(self, node_name: str):
        if node_name in self.nodes:
            self.nodes[node_name].in_flight = max(0, self.nodes[node_name].in_flight - 1)
            QUEUE_DEPTH.labels(node=node_name).set(self.nodes[node_name].in_flight)
