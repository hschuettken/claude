"""
NATS consumer for SynthesisOS daily report events.

Listens to synthesis.daily.generated topic and creates Ghost drafts.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from app.events.nats_client import NATSClient
from ghost_client import get_ghost_client
from database import SessionLocal
from models import DraftContent
from config import settings

logger = logging.getLogger(__name__)


class SynthesisConsumer:
    """Consumer for synthesis.daily.generated events."""

    def __init__(self):
        self._subscription = None
        self._running = False

    async def start(self):
        """Start listening for synthesis events."""
        if not NATSClient.is_available():
            logger.info("NATS not available — synthesis consumer will not start")
            return

        try:
            self._subscription = await NATSClient.request_subscribe(
                "synthesis.daily.generated",
                self._handle_synthesis_event,
                durable_name="marketing-synthesis-consumer"
            )
            self._running = True
            logger.info("✅ SynthesisOS consumer started — listening for synthesis.daily.generated")
            
            # Start message processing loop
            asyncio.create_task(self._process_messages())
        except Exception as e:
            logger.warning(f"Failed to start synthesis consumer: {e}")

    async def _process_messages(self):
        """Process incoming messages from the subscription."""
        if not self._subscription:
            return

        try:
            while self._running and self._subscription:
                try:
                    # NATS pull-based subscription
                    msg = await asyncio.wait_for(self._subscription.next_msg(), timeout=30)
                    
                    try:
                        # Parse the message payload
                        payload = json.loads(msg.data.decode())
                        
                        # Handle the synthesis event
                        await self._handle_synthesis_event(payload)
                        
                        # Acknowledge the message
                        await msg.ack()
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode synthesis message: {e}")
                        await msg.ack()  # Still ack to avoid reprocessing
                    except Exception as e:
                        logger.error(f"Error processing synthesis message: {e}")
                        # Don't ack on error — let NATS requeue
                except asyncio.TimeoutError:
                    # No message within timeout — continue waiting
                    continue
                except asyncio.CancelledError:
                    logger.info("SynthesisOS consumer message loop cancelled")
                    break
        except Exception as e:
            logger.error(f"SynthesisOS consumer message loop error: {e}")
        finally:
            self._running = False

    async def _handle_synthesis_event(self, payload: dict):
        """Handle a synthesis.daily.generated event."""
        try:
            title = payload.get("title", "Daily Synthesis")
            content = payload.get("content", "")
            summary = payload.get("summary", "")
            status = payload.get("status", "completed")
            generated_at = payload.get("generated_at", datetime.utcnow().isoformat())

            logger.info(f"📥 Processing synthesis event: {title}")

            # Create Ghost draft
            await self._create_ghost_draft(title, content, summary)

        except Exception as e:
            logger.error(f"Error handling synthesis event: {e}", exc_info=True)

    async def _create_ghost_draft(self, title: str, content: str, summary: str):
        """Create a Ghost draft from synthesis content."""
        try:
            if not settings.ghost_admin_api_key:
                logger.warning("Ghost API key not configured — skipping draft creation")
                return

            ghost_client = get_ghost_client()

            # Convert markdown/text to HTML (basic conversion)
            html_content = self._convert_to_html(content)

            # Create the draft
            draft = await ghost_client.create_post(
                title=title,
                html=html_content,
                tags=["synthesis"],
                status="draft",  # Always create as draft
                custom_excerpt=summary,
            )

            draft_id = draft.get("id")
            draft_url = draft.get("url")

            logger.info(f"✅ Created Ghost draft: {draft_id} — {title}")

            # Store draft info in database for frontend linking
            await self._store_synthesis_draft(title, draft_id, draft_url)

            # If SYNTHESIS_AUTO_PUBLISH is enabled, publish immediately
            if settings.synthesis_auto_publish:
                try:
                    published = await ghost_client.update_post(
                        draft_id,
                        status="published"
                    )
                    logger.info(f"✅ Published synthesis: {draft_id}")
                except Exception as e:
                    logger.warning(f"Failed to publish synthesis draft: {e}")

            await ghost_client.close()

        except Exception as e:
            logger.error(f"Failed to create Ghost draft for synthesis: {e}", exc_info=True)

    async def _store_synthesis_draft(self, title: str, draft_id: str, draft_url: str):
        """Store synthesis draft metadata in database."""
        try:
            db = SessionLocal()
            
            # Create a draft entry in DraftContent (reusing existing model)
            draft = DraftContent(
                title=title,
                excerpt=title,
                content_type="synthesis",
                status="draft",
                tags=["synthesis"],
                metadata={
                    "ghost_id": draft_id,
                    "ghost_url": draft_url,
                    "source": "synthesisOS",
                    "generated_at": datetime.utcnow().isoformat(),
                }
            )
            
            db.add(draft)
            db.commit()
            db.close()
            
            logger.debug(f"Stored synthesis draft metadata: {draft_id}")
        except Exception as e:
            logger.warning(f"Failed to store synthesis draft metadata: {e}")

    @staticmethod
    def _convert_to_html(text: str) -> str:
        """
        Basic conversion of text to HTML.
        For more sophisticated conversion, integrate markdown library.
        """
        # Simple paragraph conversion
        paragraphs = text.split("\n\n")
        html_paragraphs = [f"<p>{p.strip().replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip()]
        return "".join(html_paragraphs)

    async def stop(self):
        """Stop the consumer."""
        self._running = False
        if self._subscription:
            try:
                await self._subscription.unsubscribe()
                logger.info("SynthesisOS consumer stopped")
            except Exception as e:
                logger.warning(f"Error stopping synthesis consumer: {e}")

    def is_running(self) -> bool:
        """Check if consumer is running."""
        return self._running


# Global consumer instance
_consumer: Optional[SynthesisConsumer] = None


async def init_synthesis_consumer():
    """Initialize global synthesis consumer."""
    global _consumer
    _consumer = SynthesisConsumer()
    await _consumer.start()


def get_synthesis_consumer() -> SynthesisConsumer:
    """Get global synthesis consumer."""
    global _consumer
    if _consumer is None:
        _consumer = SynthesisConsumer()
    return _consumer


async def close_synthesis_consumer():
    """Close global synthesis consumer."""
    global _consumer
    if _consumer:
        await _consumer.stop()
        _consumer = None
