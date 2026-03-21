"""HEMS (Home Energy Management System) tool definitions and handlers.

Provides proxy tools for querying and controlling the HEMS heating system:
- Get heating status (room temps, targets, boiler state, flow temp, mode)
- Get HEMS recommendations for specific rooms or overall
- Set heating mode (auto, manual, eco, boost, off)
- Get heating schedules for rooms
- Override room target temperature
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import requests

from shared.log import get_logger

logger = get_logger("tooling.hems_tools")

HEMS_SERVICE_URL = "http://hems:8210/api/v1/hems"
HEMS_TIMEOUT = 5

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_heating_status",
            "description": (
                "Get the current heating status from HEMS: room temperatures, "
                "target temperatures, boiler state, flow temperature, and system mode."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_heating_recommendation",
            "description": (
                "Get HEMS heating recommendation for a specific room or overall system. "
                "Returns suggested actions based on current conditions and schedules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "Optional room ID. If omitted, returns overall system recommendation.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_heating_mode",
            "description": (
                "Set the heating system mode. Valid modes: auto, manual, eco, boost, off. "
                "Provide a reason for the mode change (e.g., 'user request', 'low PV forecast')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "manual", "eco", "boost", "off"],
                        "description": "Target heating mode.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for changing the mode (logged for audit).",
                    },
                },
                "required": ["mode", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hems_schedule",
            "description": (
                "Get the heating schedules for all rooms. Returns scheduled target temperatures "
                "and times for the day and upcoming days."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_room_target",
            "description": (
                "Override the target temperature for a specific room for a set duration. "
                "This temporarily overrides the schedule until the duration expires or is cleared."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "The room ID to adjust (e.g., 'living_room', 'bedroom_1').",
                    },
                    "temp_celsius": {
                        "type": "number",
                        "description": "Target temperature in Celsius (e.g., 21.5).",
                    },
                    "duration_hours": {
                        "type": "number",
                        "description": "Duration in hours to maintain this override. Use 0 to clear.",
                    },
                },
                "required": ["room_id", "temp_celsius", "duration_hours"],
            },
        },
    },
]


class HEMSTools:
    """Handler class for HEMS proxy tools."""

    def __init__(self) -> None:
        """Initialize HEMS tools (no dependencies needed)."""
        pass

    async def get_heating_status(self) -> dict[str, Any]:
        """Get current heating status from HEMS."""
        try:
            response = requests.get(
                f"{HEMS_SERVICE_URL}/status",
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error("HEMS service connection failed")
            return {"error": "HEMS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("HEMS service request timeout")
            return {"error": "HEMS service not available", "status": "offline"}
        except Exception as e:
            logger.exception("HEMS get_heating_status error")
            return {"error": str(e), "status": "error"}

    async def get_heating_recommendation(self, room_id: str | None = None) -> dict[str, Any]:
        """Get heating recommendation from HEMS."""
        try:
            params = {}
            if room_id:
                params["room_id"] = room_id

            response = requests.get(
                f"{HEMS_SERVICE_URL}/recommendation",
                params=params,
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error("HEMS service connection failed")
            return {"error": "HEMS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("HEMS service request timeout")
            return {"error": "HEMS service not available", "status": "offline"}
        except Exception as e:
            logger.exception("HEMS get_heating_recommendation error")
            return {"error": str(e), "status": "error"}

    async def set_heating_mode(self, mode: str, reason: str) -> dict[str, Any]:
        """Set heating mode via HEMS."""
        if mode not in ("auto", "manual", "eco", "boost", "off"):
            return {"error": f"Invalid mode: {mode}. Must be one of: auto, manual, eco, boost, off"}

        try:
            payload = {"mode": mode, "reason": reason}
            response = requests.post(
                f"{HEMS_SERVICE_URL}/mode",
                json=payload,
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error("HEMS service connection failed")
            return {"error": "HEMS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("HEMS service request timeout")
            return {"error": "HEMS service not available", "status": "offline"}
        except Exception as e:
            logger.exception("HEMS set_heating_mode error")
            return {"error": str(e), "status": "error"}

    async def get_hems_schedule(self) -> dict[str, Any]:
        """Get heating schedules from HEMS."""
        try:
            response = requests.get(
                f"{HEMS_SERVICE_URL}/schedule",
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error("HEMS service connection failed")
            return {"error": "HEMS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("HEMS service request timeout")
            return {"error": "HEMS service not available", "status": "offline"}
        except Exception as e:
            logger.exception("HEMS get_hems_schedule error")
            return {"error": str(e), "status": "error"}

    async def set_room_target(
        self, room_id: str, temp_celsius: float, duration_hours: float
    ) -> dict[str, Any]:
        """Set room target temperature override in HEMS."""
        try:
            payload = {
                "room_id": room_id,
                "temp_celsius": temp_celsius,
                "duration_hours": duration_hours,
            }
            response = requests.post(
                f"{HEMS_SERVICE_URL}/room-target",
                json=payload,
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error("HEMS service connection failed")
            return {"error": "HEMS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("HEMS service request timeout")
            return {"error": "HEMS service not available", "status": "offline"}
        except Exception as e:
            logger.exception("HEMS set_room_target error")
            return {"error": str(e), "status": "error"}
