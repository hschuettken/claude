"""Aggregated TOOL_DEFINITIONS — collected from all domain modules.

Import this instead of tools.py when you only need the schema list.
"""

from __future__ import annotations

from typing import Any

from tooling.ha_tools import TOOL_DEFINITIONS as _HA
from tooling.energy_tools import TOOL_DEFINITIONS as _ENERGY
from tooling.calendar_tools import TOOL_DEFINITIONS as _CALENDAR
from tooling.ev_tools import TOOL_DEFINITIONS as _EV
from tooling.memory_tools import TOOL_DEFINITIONS as _MEMORY
from tooling.notification_tools import TOOL_DEFINITIONS as _NOTIFICATION
from tooling.orbit_tools import TOOL_DEFINITIONS as _ORBIT
from tooling.hems_tools import TOOL_DEFINITIONS as _HEMS

# Weather tool definition (uses HA but doesn't warrant its own module)
_WEATHER: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Get the current weather and short-term forecast from Home Assistant.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_DEFINITIONS: list[dict[str, Any]] = (
    _HA
    + _ENERGY
    + _CALENDAR
    + _EV
    + _MEMORY
    + _NOTIFICATION
    + _ORBIT
    + _HEMS
    + _WEATHER
)
