"""Async NATS publisher for homelab event bus.

Usage (within an async context):
    from shared.nats_client import NatsPublisher

    publisher = NatsPublisher(url="nats://nats:4222")
    await publisher.connect()
    await publisher.publish("energy.pv.forecast_updated", {"today_kwh": 12.5})
    await publisher.close()

Or as context manager:
    async with NatsPublisher(url="nats://nats:4222") as pub:
        await pub.publish("energy.pv.forecast_updated", {...})
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    import nats
    import nats.aio.client

    _NATS_AVAILABLE = True
except ImportError:
    nats = None  # type: ignore[assignment]
    _NATS_AVAILABLE = False

from shared.log import get_logger

logger = get_logger("nats-publisher")


class NatsPublisher:
    """Lightweight fire-and-forget NATS publisher."""

    def __init__(self, url: str = "nats://nats:4222") -> None:
        self._url = url
        self._nc: Any | None = None

    @property
    def connected(self) -> bool:
        if not _NATS_AVAILABLE or self._nc is None:
            return False
        return not self._nc.is_closed

    async def connect(self) -> None:
        """Connect to the NATS server."""
        if not _NATS_AVAILABLE:
            logger.warning(
                "nats_unavailable",
                reason="nats-py not installed; NATS publishing disabled",
            )
            return
        try:
            self._nc = await nats.connect(self._url)
            logger.info("nats_connected", url=self._url)
        except Exception as exc:
            logger.warning("nats_connect_failed", url=self._url, error=str(exc))
            self._nc = None

    async def close(self) -> None:
        """Drain and close the NATS connection."""
        if self._nc is not None and not self._nc.is_closed:
            try:
                await self._nc.drain()
            except Exception as exc:
                logger.warning("nats_drain_failed", error=str(exc))
            self._nc = None

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        """Serialize data to JSON and publish to NATS subject.

        Silently skips if not connected — callers should not crash on
        NATS unavailability.
        """
        if not self.connected:
            logger.warning("nats_publish_skipped_not_connected", subject=subject)
            return
        try:
            payload = json.dumps(data).encode()
            await self._nc.publish(subject, payload)  # type: ignore[union-attr]
            logger.debug("nats_published", subject=subject, bytes=len(payload))
        except Exception as exc:
            logger.warning("nats_publish_failed", subject=subject, error=str(exc))

    def publish_sync(self, subject: str, data: dict[str, Any]) -> None:
        """Synchronous wrapper for publish().

        If a running event loop exists (e.g. called from a sync context inside
        an async app), schedules the coroutine thread-safely. Otherwise falls
        back to asyncio.run().
        """
        coro = self.publish(subject, data)
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            # No running loop — safe to call asyncio.run()
            asyncio.run(coro)

    async def __aenter__(self) -> "NatsPublisher":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
