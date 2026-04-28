"""Path setup for orchestrator service tests."""

from __future__ import annotations

import os
import sys

# Ensure the orchestrator service dir and shared library are importable
_ORCHESTRATOR_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)
_SHARED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared")
)

for _p in (_ORCHESTRATOR_DIR, _SHARED_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
