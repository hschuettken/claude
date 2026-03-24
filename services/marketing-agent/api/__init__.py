"""Marketing Agent API routes."""
from .signals import router as signals_router
from .topics import router as topics_router
from .drafts import router as drafts_router

__all__ = ["signals_router", "topics_router", "drafts_router"]
