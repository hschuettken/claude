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
    {
        "type": "function",
        "function": {
            "name": "activate_hems_schedule",
            "description": (
                "Activate a HEMS schedule by ID and send KNX climate control command to Home Assistant. "
                "This reads the schedule from the database and sends climate.set_temperature to the HA entity. "
                "Phase 1: Bridge between HEMS schedules and KNX heating control."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "string",
                        "description": "UUID of the HEMS schedule to activate.",
                    }
                },
                "required": ["schedule_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_thermal_training_data",
            "description": (
                "Log thermal training data (temperatures, humidity, power) to InfluxDB for HEMS model training. "
                "This data is used to improve heating predictions and system efficiency."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Room name (e.g., 'wohnzimmer', 'schlafzimmer').",
                    },
                    "current_temp": {
                        "type": "number",
                        "description": "Current room temperature in Celsius.",
                    },
                    "target_temp": {
                        "type": "number",
                        "description": "Target room temperature in Celsius.",
                    },
                    "outdoor_temp": {
                        "type": "number",
                        "description": "Optional: Outdoor temperature in Celsius.",
                    },
                    "humidity": {
                        "type": "number",
                        "description": "Optional: Relative humidity in percent.",
                    },
                    "boiler_active": {
                        "type": "boolean",
                        "description": "Optional: Whether the boiler is currently active.",
                    },
                    "power_consumption_w": {
                        "type": "number",
                        "description": "Optional: Current power consumption in watts.",
                    },
                },
                "required": ["room", "current_temp", "target_temp"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_room_target_temp",
            "description": (
                "Set a specific room's target temperature in HEMS. "
                "This sends the target to the heating control system with a reason for audit logging."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "The room ID to adjust (e.g., 'living_room', 'bedroom_1').",
                    },
                    "target_temp": {
                        "type": "number",
                        "description": "Target temperature in Celsius (e.g., 21.5).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the temperature change (logged for audit).",
                    },
                },
                "required": ["room_id", "target_temp", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_heating_analytics",
            "description": (
                "Get heating system analytics and efficiency metrics for a specified time period. "
                "Returns energy consumption, temperature trends, and system performance data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["1h", "6h", "24h", "7d", "30d"],
                        "description": "Time period for analytics (default: 24h).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_thermal_model_status",
            "description": (
                "Get the status and diagnostics of the HEMS thermal prediction model. "
                "Returns model accuracy, training status, and any issues."
            ),
            "parameters": {"type": "object", "properties": {}},
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

    async def activate_hems_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Activate a HEMS schedule and send KNX command to Home Assistant.
        
        Phase 1 implementation: calls NB9OS heating endpoint to activate schedule
        and send climate control command to HA.
        """
        nb9os_url = "http://nb9os:8060"
        endpoint = f"{nb9os_url}/api/v1/heating/schedules/{schedule_id}/activate"
        
        try:
            payload = {"confirm": True}
            response = requests.post(
                endpoint,
                json=payload,
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"HEMS schedule activated: {schedule_id}")
            return result
        except requests.exceptions.ConnectionError:
            logger.error("NB9OS service connection failed")
            return {"error": "NB9OS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("NB9OS service request timeout")
            return {"error": "NB9OS service not available", "status": "offline"}
        except Exception as e:
            logger.exception(f"HEMS activate_schedule error: {e}")
            return {"error": str(e), "status": "error"}

    async def log_thermal_training_data(
        self,
        room: str,
        current_temp: float,
        target_temp: float,
        outdoor_temp: float | None = None,
        humidity: float | None = None,
        boiler_active: bool | None = None,
        power_consumption_w: float | None = None,
    ) -> dict[str, Any]:
        """Log thermal training data to InfluxDB via NB9OS endpoint.
        
        Phase 1 implementation: calls NB9OS thermal-log endpoint to write
        training data to InfluxDB for model tuning.
        """
        nb9os_url = "http://nb9os:8060"
        endpoint = f"{nb9os_url}/api/v1/heating/thermal-log"
        
        try:
            payload = {
                "room": room,
                "current_temp": current_temp,
                "target_temp": target_temp,
            }
            if outdoor_temp is not None:
                payload["outdoor_temp"] = outdoor_temp
            if humidity is not None:
                payload["humidity"] = humidity
            if boiler_active is not None:
                payload["boiler_active"] = boiler_active
            if power_consumption_w is not None:
                payload["power_consumption_w"] = power_consumption_w
            
            response = requests.post(
                endpoint,
                json=payload,
                timeout=HEMS_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Thermal data logged: {room}")
            return result
        except requests.exceptions.ConnectionError:
            logger.error("NB9OS service connection failed")
            return {"error": "NB9OS service not available", "status": "offline"}
        except requests.exceptions.Timeout:
            logger.error("NB9OS service request timeout")
            return {"error": "NB9OS service not available", "status": "offline"}
        except Exception as e:
            logger.exception(f"HEMS log_thermal_training_data error: {e}")
            return {"error": str(e), "status": "error"}

    async def set_room_target_temp(
        self, room_id: str, target_temp: float, reason: str
    ) -> dict[str, Any]:
        """Set a specific room's target temperature in HEMS."""
        try:
            payload = {
                "target_temp": target_temp,
                "reason": reason,
            }
            response = requests.post(
                f"{HEMS_SERVICE_URL}/rooms/{room_id}/target",
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
            logger.exception("HEMS set_room_target_temp error")
            return {"error": str(e), "status": "error"}

    async def get_heating_analytics(self, period: str = "24h") -> dict[str, Any]:
        """Get heating system analytics for a specified period."""
        # Validate period
        valid_periods = ["1h", "6h", "24h", "7d", "30d"]
        if period not in valid_periods:
            period = "24h"
        
        try:
            response = requests.get(
                f"{HEMS_SERVICE_URL}/analytics/{period}",
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
            logger.exception("HEMS get_heating_analytics error")
            return {"error": str(e), "status": "error"}

    async def get_thermal_model_status(self) -> dict[str, Any]:
        """Get the status of the HEMS thermal prediction model."""
        try:
            response = requests.get(
                f"{HEMS_SERVICE_URL}/model/status",
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
            logger.exception("HEMS get_thermal_model_status error")
            return {"error": str(e), "status": "error"}
