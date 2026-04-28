"""NATS subscriber maintaining Redis hot state mirror for Kairos."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import nats
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class HotStateSubscriber:
    """
    Maintains a Redis hot state mirror indexed by user_id.

    Subscribes to NATS subjects (orbit, training, energy, synthesis, infra alerts, calendar)
    and keeps Redis keys up-to-date with the latest context for Kairos.

    Hot state structure:
    {
        "last_updated": "2026-04-12T10:00:00Z",
        "orbit": { ... latest orbit context ... },
        "training": { ... latest training event ... },
        "energy": { ... latest energy snapshot ... },
        "synthesis": { ... latest synthesis recommendations ... },
        "infra_alerts": [ ... list of recent alerts, max 5 ... ],
        "calendar": { ... upcoming events ... }
    }
    """

    def __init__(self, nats_url: str, redis_url: str) -> None:
        """Initialize NATS + Redis connections (not yet established)."""
        self.nats_url = nats_url
        self.redis_url = redis_url
        self.nc: Optional[nats.aio.client.Client] = None
        self.redis_client: Optional[redis.Redis] = None

    async def start(self) -> None:
        """Connect to NATS and Redis, subscribe to all relevant subjects."""
        logger.info("hot_state_subscriber_start")

        # Connect to NATS
        try:
            self.nc = await nats.connect(self.nats_url)
            logger.info("nats_connected", url=self.nats_url)
        except Exception as e:
            logger.error("nats_connect_failed", error=str(e))
            raise

        # Connect to Redis
        try:
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info("redis_connected", url=self.redis_url)
        except Exception as e:
            logger.error("redis_connect_failed", error=str(e))
            raise

        # Subscribe to NATS subjects
        try:
            await self.nc.subscribe("orbit.*", cb=self._handle_orbit)
            await self.nc.subscribe("training.*", cb=self._handle_training)
            await self.nc.subscribe("energy.*", cb=self._handle_energy)
            await self.nc.subscribe("synthesis.*", cb=self._handle_synthesis)
            await self.nc.subscribe("infra.alert.*", cb=self._handle_infra_alert)
            await self.nc.subscribe("calendar.*", cb=self._handle_calendar)
            await self.nc.subscribe(
                "hestia.presence.updated", cb=self._handle_hestia_presence
            )
            await self.nc.subscribe("memora.search.*", cb=self._handle_memora_search)
            logger.info("nats_subscriptions_started")
        except Exception as e:
            logger.error("nats_subscribe_failed", error=str(e))
            raise

    async def stop(self) -> None:
        """Unsubscribe + close connections."""
        logger.info("hot_state_subscriber_stop")

        if self.nc:
            try:
                await self.nc.close()
                logger.info("nats_closed")
            except Exception as e:
                logger.error("nats_close_error", error=str(e))

        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("redis_closed")
            except Exception as e:
                logger.error("redis_close_error", error=str(e))

    async def get_hot_state(self, user_id: str = "default") -> dict[str, Any]:
        """Read hot state from Redis, return empty dict if not found."""
        if not self.redis_client:
            logger.warning("get_hot_state_no_redis", user_id=user_id)
            return {}

        key = f"kairos:hot_state:{user_id}"
        try:
            data = await self.redis_client.get(key)
            if data:
                return json.loads(data)
            return {}
        except Exception as e:
            logger.error("get_hot_state_failed", user_id=user_id, error=str(e))
            return {}

    async def _update_hot_state(
        self, user_id: str, domain: str, payload: dict[str, Any]
    ) -> None:
        """Update or create hot state in Redis."""
        if not self.redis_client:
            return

        key = f"kairos:hot_state:{user_id}"
        try:
            # Get current state or init empty
            data = await self.redis_client.get(key)
            if data:
                state = json.loads(data)
            else:
                state = {}

            # Update last_updated and domain
            state["last_updated"] = datetime.now(timezone.utc).isoformat()
            state[domain] = payload

            # Serialize and store with 24h TTL
            await self.redis_client.setex(key, 86400, json.dumps(state))
            logger.debug("hot_state_updated", user_id=user_id, domain=domain)
        except Exception as e:
            logger.error(
                "update_hot_state_failed",
                user_id=user_id,
                domain=domain,
                error=str(e),
            )

    async def _append_infra_alert(self, user_id: str, alert: dict[str, Any]) -> None:
        """Append alert to rolling list (max 5), keeping newest first."""
        if not self.redis_client:
            return

        key = f"kairos:hot_state:{user_id}"
        try:
            data = await self.redis_client.get(key)
            if data:
                state = json.loads(data)
            else:
                state = {}

            # Get current alerts list or init
            alerts = state.get("infra_alerts", [])

            # Add new alert (with timestamp if not present)
            if "timestamp" not in alert:
                alert["timestamp"] = datetime.now(timezone.utc).isoformat()
            alerts.insert(0, alert)  # newest first

            # Keep only last 5
            alerts = alerts[:5]
            state["infra_alerts"] = alerts
            state["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Store with 24h TTL
            await self.redis_client.setex(key, 86400, json.dumps(state))
            logger.debug("infra_alert_appended", user_id=user_id)
        except Exception as e:
            logger.error("append_infra_alert_failed", user_id=user_id, error=str(e))

    async def _handle_orbit(self, msg: nats.msg.Msg) -> None:
        """Handle orbit.* events."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._update_hot_state(user_id, "orbit", payload)
        except json.JSONDecodeError:
            logger.warning("orbit_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_orbit_failed", subject=msg.subject, error=str(e))

    async def _handle_training(self, msg: nats.msg.Msg) -> None:
        """Handle training.* events."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._update_hot_state(user_id, "training", payload)
        except json.JSONDecodeError:
            logger.warning("training_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_training_failed", subject=msg.subject, error=str(e))

    async def _handle_energy(self, msg: nats.msg.Msg) -> None:
        """Handle energy.* events."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._update_hot_state(user_id, "energy", payload)
        except json.JSONDecodeError:
            logger.warning("energy_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_energy_failed", subject=msg.subject, error=str(e))

    async def _handle_synthesis(self, msg: nats.msg.Msg) -> None:
        """Handle synthesis.* events."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._update_hot_state(user_id, "synthesis", payload)
        except json.JSONDecodeError:
            logger.warning("synthesis_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_synthesis_failed", subject=msg.subject, error=str(e))

    async def _handle_infra_alert(self, msg: nats.msg.Msg) -> None:
        """Handle infra.alert.* events (rolling list, max 5 alerts)."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._append_infra_alert(user_id, payload)
        except json.JSONDecodeError:
            logger.warning("infra_alert_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_infra_alert_failed", subject=msg.subject, error=str(e))

    async def _handle_calendar(self, msg: nats.msg.Msg) -> None:
        """Handle calendar.* events."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            await self._update_hot_state(user_id, "calendar", payload)
        except json.JSONDecodeError:
            logger.warning("calendar_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_calendar_failed", subject=msg.subject, error=str(e))

    async def _handle_memora_search(self, msg: nats.msg.Msg) -> None:
        """Handle memora.search.* events — maintain rolling list of queries."""
        try:
            payload = json.loads(msg.data.decode())
            user_id = payload.get("user_id", "default")
            query = payload.get("query", "")
            await self._append_memora_query(user_id, query)
        except json.JSONDecodeError:
            logger.warning("memora_search_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error("handle_memora_search_failed", subject=msg.subject, error=str(e))

    async def _append_memora_query(self, user_id: str, query: str) -> None:
        """Append a Memora search query to the rolling list (max 20, newest last)."""
        if not self.redis_client:
            return

        key = f"kairos:hot_state:{user_id}"
        try:
            data = await self.redis_client.get(key)
            state = json.loads(data) if data else {}

            memora = state.get("memora", {})
            queries: list[dict] = memora.get("recent_queries", [])
            queries.append({
                "query": query,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            queries = queries[-20:]  # keep newest 20

            state["memora"] = {"recent_queries": queries}
            state["last_updated"] = datetime.now(timezone.utc).isoformat()

            await self.redis_client.setex(key, 86400, json.dumps(state))
            logger.debug("memora_query_appended", user_id=user_id, query=query[:60])
        except Exception as e:
            logger.error("append_memora_query_failed", user_id=user_id, error=str(e))

    async def _handle_hestia_presence(self, msg: nats.msg.Msg) -> None:
        """Handle hestia.presence.updated — merge presence block into hot_state for each resident."""
        try:
            payload = json.loads(msg.data.decode())
            users = payload.get("users", {})
            house_state = payload.get("house_state", "unknown")
            visitors = payload.get("visitors", {})
            updated_at = payload.get("updated_at")

            presence_data = {
                "house_state": house_state,
                "visitors_on_property": len(visitors),
                "last_change": updated_at,
                "users": {},
            }

            for uid, user_state in users.items():
                presence_data["users"][uid] = {
                    "state": user_state.get("state"),
                    "confidence": user_state.get("confidence"),
                    "last_seen_zone": user_state.get("last_seen_zone"),
                    "last_seen_at": user_state.get("last_seen_at"),
                }

            # Update hot state for each known resident
            for uid in users:
                await self._update_hot_state(uid, "presence", presence_data)

            # Also update the shared "default" slot so Kairos always has global context
            if users:
                await self._update_hot_state("default", "presence", presence_data)

            logger.debug(
                "hestia_presence_updated",
                house_state=house_state,
                residents=list(users.keys()),
                visitors=len(visitors),
            )
        except json.JSONDecodeError:
            logger.warning("hestia_presence_message_not_json", subject=msg.subject)
        except Exception as e:
            logger.error(
                "handle_hestia_presence_failed", subject=msg.subject, error=str(e)
            )
