"""SynthesisOS integration endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from app.consumers.synthesis import get_synthesis_consumer
from app.events.nats_client import NATSClient

router = APIRouter(prefix="/marketing/synthesis", tags=["synthesis"])


class SynthesisEventInput(BaseModel):
    """Input for manually triggering synthesis event."""
    title: str
    content: str
    summary: str
    status: str = "completed"


@router.get("/status", response_model=dict)
async def synthesis_status():
    """
    Get SynthesisOS consumer status.

    Returns:
    - running: Is consumer currently running
    - nats_available: Is NATS connection available
    """
    consumer = get_synthesis_consumer()
    return {
        "running": consumer.is_running(),
        "nats_available": NATSClient.is_available(),
    }


@router.post("/test-event", response_model=dict)
async def test_synthesis_event(event: SynthesisEventInput):
    """
    Manually trigger a synthesis event for testing.
    
    This endpoint publishes a synthesis.daily.generated event to NATS.
    Useful for testing the consumer without waiting for actual synthesis generation.
    
    Args:
        title: Synthesis report title
        content: Report content/body
        summary: Executive summary
        status: Event status (default: "completed")
    
    Returns:
        Event publication result
    """
    try:
        # Publish event to NATS
        payload = {
            "event": "synthesis.daily.generated",
            "title": event.title,
            "content": event.content,
            "summary": event.summary,
            "status": event.status,
            "generated_at": datetime.utcnow().isoformat(),
        }

        success = await NATSClient.publish("synthesis.daily.generated", payload)

        if not success:
            raise HTTPException(
                status_code=503,
                detail="Failed to publish synthesis event — NATS may be unavailable"
            )

        return {
            "success": True,
            "message": f"Published synthesis event: {event.title}",
            "event": payload,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish synthesis event: {str(e)}"
        )
