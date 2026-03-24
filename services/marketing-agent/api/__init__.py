"""Marketing Agent API routes."""
from .signals import router as signals_router
from .topics import router as topics_router
from .drafts import router as drafts_router
from .knowledge_graph import router as kg_router
from .kg_status import router as kg_status_router

__all__ = ["signals_router", "topics_router", "drafts_router", "kg_router", "kg_status_router"]
