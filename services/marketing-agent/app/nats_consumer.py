"""
NATS JetStream consumer for marketing-agent.

Watches for signal.detected events with relevance > 0.7, auto-creates drafts,
and sends notifications.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

logger = logging.getLogger(__name__)


class MarketingNATSConsumer:
    """
    NATS JetStream consumer for marketing signals.
    
    Subscribes to signal.detected events, filters by relevance > 0.7,
    auto-creates drafts, and sends notifications.
    """
    
    _nc: Optional[Any] = None  # nats.NATS instance
    _js: Optional[Any] = None  # nats.js.JetStreamContext instance
    _subscription: Optional[Any] = None
    _is_running: bool = False
    
    def __init__(
        self,
        db_url: str,
        nats_url: str,
        nats_user: Optional[str] = None,
        nats_password: Optional[str] = None,
        relevance_threshold: float = 0.7,
    ):
        """
        Initialize consumer.
        
        Args:
            db_url: PostgreSQL connection string
            nats_url: NATS server URL
            nats_user: NATS username (optional)
            nats_password: NATS password (optional)
            relevance_threshold: Min relevance score to process (0.0-1.0)
        """
        self.db_url = db_url
        self.nats_url = nats_url
        self.nats_user = nats_user
        self.nats_password = nats_password
        self.relevance_threshold = relevance_threshold
        self.db_engine = None
        self.db_session_maker = None
        
        logger.info(
            f"NATS Consumer initialized: "
            f"threshold={relevance_threshold}, nats={nats_url}"
        )
    
    async def connect(self) -> bool:
        """
        Connect to NATS and set up database.
        
        Returns True if successful, False otherwise.
        """
        try:
            import nats
        except ImportError:
            logger.error("nats-py not installed. Install: pip install nats-py")
            return False
        
        try:
            # Connect to NATS
            connect_kwargs = {
                "max_reconnect_attempts": 5,
                "reconnect_time_wait": 2,
            }
            if self.nats_user:
                connect_kwargs["user"] = self.nats_user
            if self.nats_password:
                connect_kwargs["password"] = self.nats_password
            
            self.__class__._nc = await nats.connect(self.nats_url, **connect_kwargs)
            self.__class__._js = self.__class__._nc.jetstream()
            
            logger.info(f"✅ NATS connected: {self.nats_url}")
            
            # Set up database
            self.db_engine = create_async_engine(
                self.db_url,
                echo=False,
                pool_size=5,
                max_overflow=10,
            )
            
            self.db_session_maker = async_sessionmaker(
                self.db_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            logger.info("✅ Database connected")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to connect: {e}")
            return False
    
    async def start(self):
        """Start consuming signal.detected events."""
        if not self._nc or not self._js:
            logger.error("Not connected to NATS. Call connect() first.")
            return
        
        try:
            # Create stream if not exists
            stream_name = "MARKETING"
            subject = "signal.detected"
            
            try:
                await self._js.add_stream(
                    name=stream_name,
                    subjects=[subject],
                )
                logger.info(f"✅ Created NATS stream: {stream_name}")
            except Exception:
                # Stream already exists
                logger.debug(f"Stream {stream_name} already exists")
            
            # Subscribe to signal.detected with durable consumer
            self._subscription = await self._js.subscribe(
                subject,
                durable="marketing-auto-draft",
                cb=self._handle_message,
            )
            
            self._is_running = True
            logger.info(f"✅ Subscribed to {subject} (relevance > {self.relevance_threshold})")
            
        except Exception as e:
            logger.error(f"❌ Failed to start consumer: {e}")
            self._is_running = False
    
    async def _handle_message(self, msg):
        """
        Handle incoming signal.detected message.
        
        Filters by relevance > threshold, auto-creates draft, sends notification.
        """
        try:
            # Decode and parse message
            payload = json.loads(msg.data.decode())
            
            logger.debug(f"📩 Received message: {payload}")
            
            # Extract fields
            event = payload.get("event")
            source = payload.get("source")
            topic = payload.get("topic")
            score = payload.get("score", 0.0)
            metadata = payload.get("metadata", {})
            
            # Filter by relevance threshold
            if score <= self.relevance_threshold:
                logger.debug(
                    f"⏭️  Skipping signal (score {score:.2f} <= {self.relevance_threshold}): {topic}"
                )
                await msg.ack()
                return
            
            logger.info(f"🎯 Processing high-relevance signal (score {score:.2f}): {topic}")
            
            # Get signal ID from metadata
            signal_id = metadata.get("id")
            if not signal_id:
                logger.warning("Signal missing ID in metadata, skipping")
                await msg.ack()
                return
            
            # Create draft
            draft_created = await self._create_draft_for_signal(
                signal_id=signal_id,
                title=topic,
                source=source,
                relevance_score=score,
                url=metadata.get("url"),
            )
            
            if draft_created:
                logger.info(f"✅ Draft created for signal {signal_id}: {topic}")
                # Send notification
                await self._send_notification(
                    signal_id=signal_id,
                    draft_id=draft_created.get("id"),
                    title=topic,
                    relevance_score=score,
                )
            else:
                logger.warning(f"⚠️  Failed to create draft for signal {signal_id}")
            
            # Acknowledge message
            await msg.ack()
        
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}", exc_info=True)
            try:
                await msg.nak()
            except:
                pass
    
    async def _create_draft_for_signal(
        self,
        signal_id: int,
        title: str,
        source: str,
        relevance_score: float,
        url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a draft from a high-relevance signal.
        
        Returns draft dict with at least 'id' key, or None if failed.
        """
        if not self.db_session_maker:
            logger.error("Database not initialized")
            return None
        
        try:
            from models import Draft, Signal, DraftStatus
            from events import publish_draft_created
            
            async with self.db_session_maker() as session:
                # Fetch the signal
                from sqlalchemy import select
                
                result = await session.execute(
                    select(Signal).where(Signal.id == signal_id)
                )
                signal = result.scalar_one_or_none()
                
                if not signal:
                    logger.warning(f"Signal {signal_id} not found in DB")
                    return None
                
                # Generate initial draft content
                # In production, this could call an LLM or template engine
                draft_content = self._generate_draft_content(
                    signal=signal,
                    title=title,
                )
                
                # Create draft
                draft = Draft(
                    title=title,
                    content=draft_content,
                    summary=f"Auto-drafted from signal: {source}",
                    signal_id=signal_id,
                    status=DraftStatus.draft,
                    tags=["auto-drafted", source, f"relevance:{relevance_score:.2f}"],
                )
                
                session.add(draft)
                await session.flush()
                
                # Publish event
                await publish_draft_created(
                    draft_id=draft.id,
                    title=draft.title,
                    tags=draft.tags,
                    source_signal=str(signal_id),
                )
                
                await session.commit()
                
                logger.info(f"Draft {draft.id} created from signal {signal_id}")
                
                return {
                    "id": draft.id,
                    "title": draft.title,
                    "signal_id": signal_id,
                }
        
        except Exception as e:
            logger.error(f"Failed to create draft: {e}", exc_info=True)
            return None
    
    def _generate_draft_content(self, signal: Any, title: str) -> str:
        """
        Generate initial draft content from signal.
        
        This is a simple template. In production, could use LLM or more sophisticated logic.
        """
        content = f"""# {title}

## Overview
{signal.snippet or "New marketing opportunity detected."}

## Source
- **URL**: {signal.url or "N/A"}
- **Domain**: {signal.source_domain or "N/A"}
- **Relevance**: {signal.relevance_score:.1%}

## Next Steps
1. Expand with original insights
2. Add examples and case studies
3. Include visuals/diagrams
4. Review for brand voice compliance
5. Submit for approval

---

_Auto-drafted from signal {signal.id} — Please edit and expand._
"""
        return content
    
    async def _send_notification(
        self,
        signal_id: int,
        draft_id: int,
        title: str,
        relevance_score: float,
    ):
        """
        Send notification about auto-created draft.
        
        Currently logs; can be extended to send Discord/email/Telegram notifications.
        """
        message = (
            f"🚀 Auto-drafted new post\n"
            f"📌 Signal #{signal_id}\n"
            f"📄 Draft #{draft_id}\n"
            f"📝 {title}\n"
            f"🎯 Relevance: {relevance_score:.1%}"
        )
        
        logger.info(f"📢 Notification: {message}")
        
        # TODO: Send to Discord/email/Telegram if configured
        # For now, just log it
    
    async def stop(self):
        """Stop consuming and close connections."""
        self._is_running = False
        
        if self._subscription:
            try:
                await self._subscription.unsubscribe()
                logger.info("Unsubscribed from NATS stream")
            except Exception as e:
                logger.warning(f"Error unsubscribing: {e}")
        
        if self._nc:
            try:
                await self._nc.close()
                logger.info("NATS connection closed")
            except Exception as e:
                logger.warning(f"Error closing NATS: {e}")
        
        if self.db_engine:
            try:
                await self.db_engine.dispose()
                logger.info("Database connection closed")
            except Exception as e:
                logger.warning(f"Error closing DB: {e}")
        
        self.__class__._nc = None
        self.__class__._js = None
    
    def is_running(self) -> bool:
        """Check if consumer is actively running."""
        return self._is_running


async def run_consumer():
    """Standalone consumer runner for local development/testing."""
    
    # Get config from env
    db_url = os.getenv(
        "MARKETING_DB_URL",
        "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab",
    )
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    nats_user = os.getenv("NATS_USER")
    nats_password = os.getenv("NATS_PASSWORD")
    relevance_threshold = float(os.getenv("SIGNAL_RELEVANCE_THRESHOLD", "0.7"))
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Create and run consumer
    consumer = MarketingNATSConsumer(
        db_url=db_url,
        nats_url=nats_url,
        nats_user=nats_user,
        nats_password=nats_password,
        relevance_threshold=relevance_threshold,
    )
    
    if not await consumer.connect():
        logger.error("Failed to connect to NATS/DB")
        return
    
    await consumer.start()
    
    try:
        # Keep running
        while consumer.is_running():
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run_consumer())
