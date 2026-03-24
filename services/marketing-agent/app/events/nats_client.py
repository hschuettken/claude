"""
Shared NATS JetStream client for event publishing and consuming.

All services gracefully degrade if NATS is unavailable.
"""

import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class NATSClient:
    """
    Singleton NATS client with graceful degradation.
    
    If NATS connection fails or is not configured, all operations
    become no-ops and services continue normally with a warning log.
    """
    
    _nc: Optional[Any] = None  # nats.NATS instance
    _js: Optional[Any] = None  # nats.js.JetStreamContext instance
    _is_available: bool = False
    
    @classmethod
    async def connect(cls, url: str, user: str, password: str) -> bool:
        """
        Initialize connection to NATS JetStream.
        
        Returns True if connected, False if unavailable (graceful degrade).
        """
        try:
            import nats
        except ImportError:
            logger.warning("nats-py not installed — NATS events disabled. Install: pip install nats-py")
            cls._is_available = False
            return False
        
        try:
            cls._nc = await nats.connect(
                url,
                user=user,
                password=password,
                max_reconnect_attempts=3,
                reconnect_time_wait=2
            )
            cls._js = cls._nc.jetstream()
            cls._is_available = True
            logger.info(f"✅ NATS connected: {url}")
            return True
        except Exception as e:
            logger.warning(f"⚠️  NATS unavailable ({url}): {e} — running without event bus")
            cls._nc = None
            cls._js = None
            cls._is_available = False
            return False
    
    @classmethod
    async def publish(cls, subject: str, payload: Dict[str, Any]) -> bool:
        """
        Publish a message to a NATS subject.
        
        Returns True if published, False if unavailable or error.
        Always returns gracefully (no exceptions).
        """
        if cls._js is None:
            return False
        
        try:
            message = json.dumps(payload).encode()
            await cls._js.publish(subject, message)
            logger.debug(f"📤 Published to {subject}: {json.dumps(payload)[:100]}")
            return True
        except Exception as e:
            logger.warning(f"⚠️  NATS publish failed ({subject}): {e}")
            return False
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if NATS is currently connected and available."""
        if cls._nc is None:
            return False
        try:
            return cls._nc.is_connected
        except:
            return False
    
    @classmethod
    async def close(cls):
        """Close NATS connection gracefully."""
        if cls._nc:
            try:
                await cls._nc.close()
                logger.info("NATS connection closed")
            except:
                pass
            cls._nc = None
            cls._js = None
            cls._is_available = False
    
    @classmethod
    async def request_subscribe(
        cls, 
        subject: str, 
        handler,
        durable_name: Optional[str] = None
    ) -> Optional[Any]:
        """
        Subscribe to a subject with a durable consumer.
        
        Returns subscription object or None if unavailable.
        """
        if cls._js is None:
            return None
        
        try:
            sub = await cls._js.subscribe(subject, durable=durable_name)
            logger.info(f"📥 Subscribed to {subject} (durable={durable_name})")
            return sub
        except Exception as e:
            logger.warning(f"⚠️  NATS subscribe failed ({subject}): {e}")
            return None
