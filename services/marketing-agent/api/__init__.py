"""Marketing Agent API routes."""
from .signals import router as signals_router
from .topics import router as topics_router
from .drafts import router as drafts_router
from .approval import router as approval_router
from .knowledge_graph import router as kg_router
from .kg_status import router as kg_status_router
from .publish import router as publish_router
from .scout import router as scout_router
from .storylines import router as storylines_router
from .draft_studio import router as draft_studio_router
from .performance_pulse import router as performance_pulse_router

__all__ = [
    "signals_router",
    "topics_router",
    "drafts_router",
    "approval_router",
    "kg_router",
    "kg_status_router",
    "publish_router",
    "scout_router",
    "storylines_router",
    "draft_studio_router",
    "performance_pulse_router",
]
