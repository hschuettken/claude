"""HEMS dry-run flag (#1051).

Module-level flag read from HEMS_DRY_RUN env var.
When enabled, actuation commands are logged but not executed.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("hems.dry_run")

DRY_RUN: bool = os.getenv("HEMS_DRY_RUN", "false").lower() in ("1", "true", "yes")


def is_dry_run() -> bool:
    """Return True if HEMS is running in dry-run mode."""
    return DRY_RUN


def gate_actuation(action_name: str) -> bool:
    """Gate an actuation action through the dry-run flag.

    Returns True if the action should proceed, False if suppressed.
    Logs the suppressed action when in dry-run mode.
    """
    if DRY_RUN:
        logger.info("[DRY_RUN] would execute: %s", action_name)
        return False
    return True
