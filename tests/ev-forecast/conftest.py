"""Shared fixtures for ev-forecast tests."""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, AsyncMock

import pytest

# Add ev-forecast service and shared library to path
SERVICE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "ev-forecast")
)
SHARED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)

if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)


def make_ha_client() -> MagicMock:
    """Return a MagicMock HomeAssistantClient."""
    ha = MagicMock()
    ha.get_state = AsyncMock(return_value={"state": "unknown"})
    ha.call_service = AsyncMock(return_value=None)
    return ha


@pytest.fixture
def ha():
    return make_ha_client()


@pytest.fixture
def known_destinations():
    return {
        "Münster": 60.0,
        "Aachen": 80.0,
        "Lengerich": 22.0,
        "Köln": 100.0,
        "Hamburg": 300.0,
        "STR": 500.0,
        "Stuttgart": 500.0,
    }
