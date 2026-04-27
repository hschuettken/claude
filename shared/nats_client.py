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
        """Connect to the NATS server.

        FR #3068: configure nats-py for indefinite reconnect with explicit
        callbacks so transient disconnects don't silently drop subscriptions.
        Without this, the default nats-py behavior gives up after 60 attempts
        and silently flips ``_nc.is_closed=True`` — which makes every
        subsequent ``publish``/``subscribe`` a no-op without surfacing why.
        """
        if not _NATS_AVAILABLE:
            logger.warning(
                "nats_unavailable",
                reason="nats-py not installed; NATS publishing disabled",
            )
            return

        async def _on_disconnect() -> None:
            logger.warning("nats_disconnected", url=self._url)

        async def _on_reconnect() -> None:
            logger.info("nats_reconnected", url=self._url)

        async def _on_closed() -> None:
            logger.warning("nats_closed", url=self._url)

        async def _on_error(err: Exception) -> None:
            logger.warning("nats_error", url=self._url, error=str(err))

        try:
            self._nc = await nats.connect(
                self._url,
                max_reconnect_attempts=-1,  # never give up
                reconnect_time_wait=2,  # 2 s between attempts
                ping_interval=20,
                max_outstanding_pings=5,
                disconnected_cb=_on_disconnect,
                reconnected_cb=_on_reconnect,
                closed_cb=_on_closed,
                error_cb=_on_error,
            )
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

    async def subscribe(self, subject: str, callback) -> None:
        """Subscribe to a subject; callback receives raw nats.Msg."""
        if not self.connected:
            logger.warning("nats_subscribe_skipped_not_connected", subject=subject)
            return
        await self._nc.subscribe(subject, cb=callback)  # type: ignore[union-attr]
        logger.info("nats_subscribed", subject=subject)

    async def subscribe_json(self, subject: str, callback) -> None:
        """Subscribe to a subject; callback receives (subject: str, payload: dict)."""
        if not self.connected:
            logger.warning("nats_subscribe_skipped_not_connected", subject=subject)
            return

        async def _wrapper(msg: Any) -> None:
            try:
                data = json.loads(msg.data.decode())
                await callback(msg.subject, data)
            except Exception as exc:
                logger.warning(
                    "nats_callback_failed", subject=msg.subject, error=str(exc)
                )

        await self._nc.subscribe(subject, cb=_wrapper)  # type: ignore[union-attr]
        logger.info("nats_subscribed", subject=subject)

    async def publish_ha_discovery(
        self,
        component: str,
        object_id: str,
        node_id: str,
        config: dict[str, Any],
    ) -> None:
        """Publish HA auto-discovery config via NATS.

        Subject: ha.discovery.{component}.{node_id}.{object_id}
        The nats-mqtt-bridge appends /config when forwarding to the MQTT broker,
        producing homeassistant/{component}/{node_id}/{object_id}/config.
        Pass node_id="" to omit the node segment.
        """
        if node_id:
            subject = f"ha.discovery.{component}.{node_id}.{object_id}"
        else:
            subject = f"ha.discovery.{component}.{object_id}"
        await self.publish(subject, config)

    async def publish_status(self, service_name: str, data: dict[str, Any]) -> None:
        """Publish service status to energy.{service_name}.status."""
        await self.publish(f"energy.{service_name}.status", data)

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
