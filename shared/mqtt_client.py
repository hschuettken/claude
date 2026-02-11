"""MQTT client wrapper for inter-service messaging.

Provides a simple pub/sub interface. Services use MQTT topics to
communicate without direct dependencies on each other.

Topic convention:
    homelab/{service_name}/{event_type}

Examples:
    homelab/energy-monitor/price-changed
    homelab/climate-control/setpoint-updated

Usage:
    import asyncio
    from shared.mqtt_client import MQTTClient
    from shared.config import Settings

    settings = Settings()
    mqtt = MQTTClient(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id="my-service",
    )

    # Subscribe and handle messages
    def on_price_change(topic, payload):
        print(f"Price changed: {payload}")

    mqtt.subscribe("homelab/energy-monitor/price-changed", on_price_change)
    mqtt.connect()

    # Publish from another service
    mqtt.publish("homelab/energy-monitor/price-changed", {"price": 0.28, "unit": "EUR/kWh"})
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from shared.log import get_logger

logger = get_logger("mqtt-client")

MessageHandler = Callable[[str, dict[str, Any]], None]


class MQTTClient:
    """Simple MQTT pub/sub client wrapping paho-mqtt."""

    def __init__(
        self,
        host: str = "mqtt",
        port: int = 1883,
        client_id: str = "",
        username: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self._client_id = client_id
        self._handlers: dict[str, list[MessageHandler]] = {}

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any, properties: Any = None) -> None:
        logger.info("mqtt_connected", host=self.host, port=self.port)
        # Re-subscribe on reconnect
        for topic in self._handlers:
            self._client.subscribe(topic)

    def _on_message(self, client: Any, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": msg.payload.decode(errors="replace")}

        handlers = self._handlers.get(msg.topic, [])
        # Also check wildcard subscriptions
        for pattern, pattern_handlers in self._handlers.items():
            if "#" in pattern or "+" in pattern:
                if mqtt.topic_matches_sub(pattern, msg.topic):
                    handlers = handlers + pattern_handlers

        for handler in handlers:
            try:
                handler(msg.topic, payload)
            except Exception as exc:
                logger.exception("mqtt_handler_error", topic=msg.topic)
                # Publish to dead-letter topic for observability/replay
                self._publish_error(msg.topic, payload, exc)

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """Register a handler for a topic (supports MQTT wildcards)."""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        if self._client.is_connected():
            self._client.subscribe(topic)

    def publish(self, topic: str, payload: dict[str, Any] | str) -> None:
        """Publish a JSON message to a topic."""
        data = json.dumps(payload) if isinstance(payload, dict) else payload
        self._client.publish(topic, data)

    def connect(self) -> None:
        """Connect and start the network loop (blocking)."""
        self._client.connect(self.host, self.port)
        logger.info("mqtt_starting_loop")
        self._client.loop_forever()

    def connect_background(self) -> None:
        """Connect and start the network loop in a background thread."""
        self._client.connect(self.host, self.port)
        self._client.loop_start()

    def publish_ha_discovery(
        self,
        component: str,
        object_id: str,
        config: dict[str, Any],
        node_id: str = "",
    ) -> None:
        """Publish an HA MQTT auto-discovery config message.

        HA automatically creates an entity when it sees a config message on
        the discovery topic. No manual HA config or restart needed.

        Args:
            component: HA platform type (e.g. "sensor", "binary_sensor").
            object_id: Unique ID for this entity (e.g. "pv_forecast_status").
            config: HA discovery config dict (name, state_topic, etc.).
            node_id: Optional grouping node (e.g. "pv_forecast").
        """
        if node_id:
            topic = f"homeassistant/{component}/{node_id}/{object_id}/config"
        else:
            topic = f"homeassistant/{component}/{object_id}/config"

        # Ensure unique_id is set (required for entity registry)
        if "unique_id" not in config:
            config["unique_id"] = f"{node_id}_{object_id}" if node_id else object_id

        self._client.publish(topic, json.dumps(config), retain=True)
        logger.info("ha_discovery_published", component=component, object_id=object_id)

    def _publish_error(self, original_topic: str, payload: Any, exc: Exception) -> None:
        """Publish failed message metadata to a dead-letter error topic."""
        try:
            error_payload = json.dumps({
                "original_topic": original_topic,
                "original_payload": payload if isinstance(payload, dict) else str(payload),
                "error": str(exc),
                "error_type": type(exc).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": self._client_id,
            })
            self._client.publish(
                f"homelab/errors/{self._client_id}",
                error_payload,
            )
        except Exception:
            pass  # Don't let error reporting cause more errors

    def disconnect(self) -> None:
        """Stop the loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()
