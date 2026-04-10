"""HEMS configuration loader from envctl (#1050).

Loads HEMS_ prefixed config from envctl at startup with os.environ fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("hems.envctl_config")

ENVCTL_URL = "http://192.168.0.50:8201"
ENVCTL_API_KEY = "super_secure_api_key"

# Module-level config cache populated by load_hems_config()
_config_cache: dict[str, str] = {}


async def load_hems_config() -> dict[str, str]:
    """Fetch HEMS_ prefixed config entries from envctl.

    Falls back to os.environ if envctl is unreachable.
    Populates the module-level cache for sync access via get_config().
    """
    global _config_cache

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ENVCTL_URL}/config",
                params={"service": "hems"},
                headers={"X-API-Key": ENVCTL_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()

        # envctl may return a list of {key, value} objects or a flat dict
        if isinstance(data, list):
            entries = {
                item["key"]: item["value"]
                for item in data
                if isinstance(item, dict) and "key" in item and "value" in item
            }
        elif isinstance(data, dict):
            entries = {k: v for k, v in data.items() if isinstance(v, str)}
        else:
            entries = {}

        # Filter to HEMS_ prefixed keys
        hems_entries = {k: v for k, v in entries.items() if k.startswith("HEMS_")}
        _config_cache = hems_entries
        logger.info("Loaded %d HEMS config entries from envctl", len(hems_entries))
        return hems_entries

    except Exception as exc:
        logger.warning("envctl unreachable (%s), falling back to os.environ", exc)
        hems_env = {k: v for k, v in os.environ.items() if k.startswith("HEMS_")}
        _config_cache = hems_env
        return hems_env


def get_config(key: str, default: Optional[Any] = None) -> Optional[Any]:
    """Synchronous lookup in the loaded config cache.

    Falls back to os.environ if the cache hasn't been populated or the key
    is absent from it.
    """
    if key in _config_cache:
        return _config_cache[key]
    return os.environ.get(key, default)
