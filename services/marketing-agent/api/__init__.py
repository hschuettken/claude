"""Marketing Agent API routes."""
import sys
from importlib import import_module

def __getattr__(name):
    """Lazy-load routers to avoid circular imports."""
    router_map = {
        "signals_router": (".signals", "router"),
        "topics_router": (".topics", "router"),
        "drafts_router": (".drafts", "router"),
        "approval_router": (".approval", "router"),
        "kg_router": (".knowledge_graph", "router"),
        "kg_status_router": (".kg_status", "router"),
        "scout_router": (".scout", "router"),
        "routing_router": (".routing", "router"),
        "metaphor_router": ("..app.metaphor_engine", "router"),
    }
    
    if name in router_map:
        module_path, attr_name = router_map[name]
        try:
            module = import_module(module_path, __package__)
            return getattr(module, attr_name)
        except ImportError as e:
            raise AttributeError(f"Cannot import {name}: {e}")
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "signals_router",
    "topics_router",
    "drafts_router",
    "approval_router",
    "kg_router",
    "kg_status_router",
    "scout_router",
    "routing_router",
    "metaphor_router",
]
