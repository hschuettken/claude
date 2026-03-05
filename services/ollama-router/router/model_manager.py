"""Model lifecycle: preload, unload, pull, keep-alive, auto-unload."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .config import Settings
from .node_manager import NodeManager

logger = logging.getLogger("ollama-router.models")


class ModelManager:
    def __init__(self, settings: Settings, node_manager: NodeManager):
        self.settings = settings
        self.nm = node_manager
        self._client: httpx.AsyncClient | None = None
        self._unload_task: asyncio.Task | None = None
        # Track last-used time per (model, node)
        self._last_used: dict[tuple[str, str], float] = {}

    async def start(self):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        if self.settings.lifecycle.preload_on_startup:
            asyncio.create_task(self._preload_defaults())
        self._unload_task = asyncio.create_task(self._auto_unload_loop())
        logger.info("Model manager started")

    async def stop(self):
        if self._unload_task:
            self._unload_task.cancel()
            try:
                await self._unload_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    def touch(self, model: str, node: str):
        """Record that a model was used on a node."""
        self._last_used[(model, node)] = time.time()

    async def preload(self, model: str, node_name: str) -> bool:
        """Load a model into memory on a specific node."""
        assert self._client
        ns = self.nm.nodes.get(node_name)
        if not ns:
            return False
        try:
            resp = await self._client.post(
                f"{ns.url}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": "15m"},
                timeout=120.0,
            )
            resp.raise_for_status()
            logger.info("Preloaded %s on %s", model, node_name)
            self.touch(model, node_name)
            return True
        except Exception as e:
            logger.error("Failed to preload %s on %s: %s", model, node_name, e)
            return False

    async def unload(self, model: str, node_name: str) -> bool:
        """Unload a model from memory on a specific node."""
        assert self._client
        ns = self.nm.nodes.get(node_name)
        if not ns:
            return False
        try:
            resp = await self._client.post(
                f"{ns.url}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": 0},
                timeout=30.0,
            )
            resp.raise_for_status()
            logger.info("Unloaded %s from %s", model, node_name)
            self._last_used.pop((model, node_name), None)
            return True
        except Exception as e:
            logger.error("Failed to unload %s from %s: %s", model, node_name, e)
            return False

    async def pull(self, model: str, node_name: str) -> bool:
        """Pull a model on a specific node."""
        assert self._client
        ns = self.nm.nodes.get(node_name)
        if not ns:
            return False
        try:
            resp = await self._client.post(
                f"{ns.url}/api/pull",
                json={"name": model, "stream": False},
                timeout=600.0,
            )
            resp.raise_for_status()
            logger.info("Pulled %s on %s", model, node_name)
            return True
        except Exception as e:
            logger.error("Failed to pull %s on %s: %s", model, node_name, e)
            return False

    async def _preload_defaults(self):
        """Preload default models on startup after initial health check."""
        await asyncio.sleep(15)  # Wait for first health poll
        for nc in self.settings.nodes:
            for model in nc.default_models:
                ns = self.nm.nodes.get(nc.name)
                if ns and model in ns.available_models:
                    await self.preload(model, nc.name)

    async def _auto_unload_loop(self):
        idle_mins = self.settings.lifecycle.idle_unload_minutes
        while True:
            await asyncio.sleep(60)
            now = time.time()
            cutoff = now - idle_mins * 60
            to_unload = [
                (model, node) for (model, node), last in self._last_used.items()
                if last < cutoff
            ]
            for model, node in to_unload:
                logger.info("Auto-unloading idle model %s from %s", model, node)
                await self.unload(model, node)
