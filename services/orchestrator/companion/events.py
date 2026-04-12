"""NATS event publisher for Kairos companion agent."""

import logging
from datetime import datetime, timezone
from typing import Optional

import nats
from nats.aio.client import Client as NATSClient

logger = logging.getLogger(__name__)


class KairosEventPublisher:
    """Publishes Kairos conversation events to NATS JetStream.

    All publish failures are non-fatal — errors are logged and execution continues.
    """

    def __init__(self, nats_url: str = "nats://192.168.0.50:4222") -> None:
        self._nats_url = nats_url
        self._nc: Optional[NATSClient] = None

    async def connect(self) -> None:
        """Connect to NATS. Non-fatal if connection fails."""
        try:
            self._nc = await nats.connect(self._nats_url)
            logger.info("kairos_events_nats_connected", url=self._nats_url)
        except Exception as exc:
            logger.warning("kairos_events_nats_connect_failed", error=str(exc))
            self._nc = None

    async def close(self) -> None:
        """Drain and close NATS connection."""
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception as exc:
                logger.warning("kairos_events_nats_drain_failed", error=str(exc))
            self._nc = None

    async def publish(self, subject: str, data: dict) -> None:
        """Publish event to NATS. Log on failure but don't raise."""
        if self._nc is None or not self._nc.is_connected:
            logger.debug("kairos_events_nats_not_connected", subject=subject)
            return
        try:
            import json as _json

            payload = _json.dumps(data).encode()
            await self._nc.publish(subject, payload)
        except Exception as exc:
            logger.warning(
                "kairos_events_publish_failed", subject=subject, error=str(exc)
            )

    def _base_event(self, event: str, user_id: str, session_id: str) -> dict:
        return {
            "event": event,
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    async def conversation_started(self, user_id: str, session_id: str) -> None:
        """Emit kairos.conversation.started when a new session is created."""
        evt = self._base_event("kairos.conversation.started", user_id, session_id)
        evt["data"] = {}
        await self.publish("kairos.conversation.started", evt)

    async def message_received(
        self, user_id: str, session_id: str, token_count: int
    ) -> None:
        """Emit kairos.conversation.message when a user message arrives."""
        evt = self._base_event("kairos.conversation.message", user_id, session_id)
        evt["data"] = {"token_count": token_count}
        await self.publish("kairos.conversation.message", evt)

    async def response_sent(
        self,
        user_id: str,
        session_id: str,
        token_count: int,
        latency_ms: int,
    ) -> None:
        """Emit kairos.conversation.response when Kairos responds."""
        evt = self._base_event("kairos.conversation.response", user_id, session_id)
        evt["data"] = {"token_count": token_count, "latency_ms": latency_ms}
        await self.publish("kairos.conversation.response", evt)

    async def tool_called(
        self,
        user_id: str,
        session_id: str,
        tool_name: str,
        success: bool,
    ) -> None:
        """Emit kairos.tool.called when a tool is executed."""
        evt = self._base_event("kairos.tool.called", user_id, session_id)
        evt["data"] = {"tool_name": tool_name, "success": success}
        await self.publish("kairos.tool.called", evt)

    async def dispatch_created(
        self, user_id: str, session_id: str, dispatch_id: str
    ) -> None:
        """Emit kairos.dispatch.created when a Claude Code dispatch is queued."""
        evt = self._base_event("kairos.dispatch.created", user_id, session_id)
        evt["data"] = {"dispatch_id": dispatch_id}
        await self.publish("kairos.dispatch.created", evt)

    async def cost_warning(
        self,
        user_id: str,
        pct_used: float,
        tokens_used: int,
        cap: int,
    ) -> None:
        """Emit kairos.cost.warning when daily usage exceeds warning threshold (80%)."""
        evt = {
            "event": "kairos.cost.warning",
            "user_id": user_id,
            "session_id": "",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {
                "pct_used": pct_used,
                "tokens_used": tokens_used,
                "cap": cap,
            },
        }
        await self.publish("kairos.cost.warning", evt)

    async def cap_reached(
        self,
        user_id: str,
        tokens_used: int,
        cap: int,
    ) -> None:
        """Emit kairos.cost.cap_reached when daily cap is hit."""
        evt = {
            "event": "kairos.cost.cap_reached",
            "user_id": user_id,
            "session_id": "",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {
                "tokens_used": tokens_used,
                "cap": cap,
            },
        }
        await self.publish("kairos.cost.cap_reached", evt)
