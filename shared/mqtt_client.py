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
from typing import Any

import paho.mqtt.client as mqtt

from shared.logging import get_logger

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
            except Exception:
                logger.exception("mqtt_handler_error", topic=msg.topic)

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

    def disconnect(self) -> None:
        """Stop the loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()
