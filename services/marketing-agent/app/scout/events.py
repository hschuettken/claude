"""NATS and MQTT event publishing for scout signals."""

import json
import logging
from datetime import datetime
from typing import Optional

from app.events.nats_client import NATSClient

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """MQTT publisher for scout signal events to bridge NATS."""
    
    def __init__(self, mqtt_host: str = "192.168.0.50", mqtt_port: int = 1883):
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port
        self._mqtt_available = False
        self._client = None
    
    async def initialize(self):
        """Initialize MQTT connection."""
        try:
            import paho.mqtt.client as mqtt
            
            def on_connect(client, userdata, flags, rc, properties=None):
                if rc == 0:
                    logger.info(f"✅ MQTT connected to {self._mqtt_host}:{self._mqtt_port}")
                    self._mqtt_available = True
                else:
                    logger.warning(f"MQTT connection failed with code {rc}")
                    self._mqtt_available = False
            
            def on_disconnect(client, userdata, flags, rc, properties=None):
                logger.info("MQTT disconnected")
                self._mqtt_available = False
            
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="marketing-agent-scout"
            )
            self._client.on_connect = on_connect
            self._client.on_disconnect = on_disconnect
            
            # Non-blocking connect
            self._client.connect_async(self._mqtt_host, self._mqtt_port, keepalive=60)
            self._client.loop_start()
            
        except ImportError:
            logger.warning("paho-mqtt not installed — MQTT events disabled. Install: pip install paho-mqtt")
            self._mqtt_available = False
        except Exception as e:
            logger.warning(f"Failed to initialize MQTT: {e}")
            self._mqtt_available = False
    
    async def publish_signal_detected(
        self,
        signal_id: int,
        title: str,
        url: str,
        pillar_id: Optional[int],
        relevance_score: float,
        detected_at: Optional[datetime] = None,
    ) -> bool:
        """Publish signal detection event via MQTT."""
        if not self._mqtt_available or not self._client:
            return False
        
        if detected_at is None:
            detected_at = datetime.utcnow()
        
        payload = {
            "event": "signal.detected",
            "signal_id": signal_id,
            "title": title,
            "url": url,
            "pillar_id": pillar_id,
            "relevance_score": relevance_score,
            "detected_at": detected_at.isoformat(),
        }
        
        try:
            # Publish to MQTT topic that acts as NATS bridge
            self._client.publish(
                "marketing/signal/detected",
                json.dumps(payload),
                qos=1,
                retain=False
            )
            logger.debug(f"📤 Published via MQTT: signal {signal_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to publish MQTT event: {e}")
            return False
    
    async def close(self):
        """Close MQTT connection."""
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
                logger.info("MQTT connection closed")
            except Exception as e:
                logger.warning(f"Error closing MQTT: {e}")


class NATSPublisher:
    """Publisher for scout signal events with graceful fallback."""

    def __init__(self):
        self._nats_available = False
        self._mqtt_publisher = MQTTPublisher()

    async def initialize(self, nats_url: Optional[str]):
        """Initialize NATS and MQTT connections."""
        if not nats_url:
            logger.info("NATS_URL not configured — NATS event publishing disabled")
            self._nats_available = False
        else:
            connected = await NATSClient.connect(nats_url, user="", password="")
            self._nats_available = connected
        
        # Always initialize MQTT as fallback/bridge
        await self._mqtt_publisher.initialize()

    async def publish_signal_detected(
        self,
        signal_id: int,
        title: str,
        url: str,
        pillar_id: Optional[int],
        relevance_score: float,
        detected_at: Optional[datetime] = None,
    ) -> bool:
        """
        Publish a signal.detected event to NATS and MQTT.

        Called when a new signal is detected by scout.
        Gracefully falls back if both are unavailable.
        
        Returns True if published to at least one destination, False if both unavailable.
        """
        if detected_at is None:
            detected_at = datetime.utcnow()

        payload = {
            "event": "signal.detected",
            "signal_id": signal_id,
            "title": title,
            "url": url,
            "pillar_id": pillar_id,
            "relevance_score": relevance_score,
            "detected_at": detected_at.isoformat(),
        }

        # Try NATS first
        nats_success = False
        if self._nats_available:
            try:
                nats_success = await NATSClient.publish("marketing.signals.detected", payload)
                if nats_success:
                    logger.debug(f"📤 Published to NATS: signal {signal_id}")
            except Exception as e:
                logger.warning(f"Failed to publish to NATS: {e}")
        
        # Try MQTT as fallback/bridge
        mqtt_success = await self._mqtt_publisher.publish_signal_detected(
            signal_id, title, url, pillar_id, relevance_score, detected_at
        )
        
        return nats_success or mqtt_success

    async def close(self):
        """Close NATS and MQTT connections."""
        await NATSClient.close()
        await self._mqtt_publisher.close()

    def is_available(self) -> bool:
        """Check if any event bus is available."""
        nats_available = self._nats_available and NATSClient.is_available()
        return nats_available or (self._mqtt_publisher._client is not None and self._mqtt_publisher._mqtt_available)


# Global publisher instance
_publisher: Optional[NATSPublisher] = None


async def init_nats_publisher(nats_url: Optional[str]):
    """Initialize global NATS publisher."""
    global _publisher
    _publisher = NATSPublisher()
    await _publisher.initialize(nats_url)


def get_nats_publisher() -> NATSPublisher:
    """Get global NATS publisher."""
    global _publisher
    if _publisher is None:
        _publisher = NATSPublisher()
    return _publisher


async def close_nats_publisher():
    """Close global NATS publisher."""
    global _publisher
    if _publisher:
        await _publisher.close()
        _publisher = None


async def on_signal_detected(
    signal_id: int,
    title: str,
    url: str,
    pillar_id: Optional[int],
    relevance_score: float,
    detected_at: Optional[datetime] = None,
):
    """
    Publish a signal.detected event to NATS.

    Called when a new signal is detected by scout.
    Gracefully falls back if NATS is unavailable.
    """
    publisher = get_nats_publisher()
    await publisher.publish_signal_detected(signal_id, title, url, pillar_id, relevance_score, detected_at)
