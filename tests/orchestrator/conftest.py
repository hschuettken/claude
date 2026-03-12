"""Fixtures for orchestrator tests."""

from __future__ import annotations

import sys
import os

# Add orchestrator service dir to path
SERVICE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "orchestrator")
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

# Also add the shared dir
SHARED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
