"""Scout Engine — Scout configuration and initialization."""

from .searxng_client import SearXNGClient, SearchResult
from .scorer import score_signal
from .scheduler import ScoutScheduler, SearchProfile, load_profiles, run_scout_profile, get_scheduler, set_scheduler

__all__ = [
    "SearXNGClient",
    "SearchResult",
    "score_signal",
    "ScoutScheduler",
    "SearchProfile",
    "load_profiles",
    "run_scout_profile",
    "get_scheduler",
    "set_scheduler",
]
