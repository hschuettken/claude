"""Test fixtures for digital-twin tests."""
from __future__ import annotations

import os
import sys

# Ensure service package is importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Ensure shared/ is importable (parent of services/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
