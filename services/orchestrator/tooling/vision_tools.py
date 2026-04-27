"""Vision tool definitions and handlers — camera snapshot access via Home Assistant."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger

logger = get_logger("tooling.vision_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_cameras",
            "description": (
                "List all camera entities available in Home Assistant. "
                "Use this to discover camera entity IDs before calling get_camera_snapshot."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_camera_snapshot",
            "description": (
                "Fetch a current snapshot image from a Home Assistant camera entity. "
                "The image is included in the response and visible to vision-capable models. "
                "Use list_cameras first to discover available camera entity IDs. "
                "Examples: 'Was ist gerade an der Haustür?', 'Zeig mir die Kamera vorne'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_entity_id": {
                        "type": "string",
                        "description": "Full camera entity ID, e.g. camera.front_door or camera.reolink_elite",
                    },
                },
                "required": ["camera_entity_id"],
            },
        },
    },
]


class VisionTools:
    """Handlers for camera vision tools."""

    def __init__(self, ha: HomeAssistantClient) -> None:
        self.ha = ha

    async def list_cameras(self) -> dict[str, Any]:
        """List all camera entities in Home Assistant."""
        try:
            entities = await self.ha.get_states()
        except Exception as exc:
            return {"error": str(exc), "cameras": []}

        cameras = [
            {
                "entity_id": e["entity_id"],
                "friendly_name": e.get("attributes", {}).get("friendly_name"),
                "state": e.get("state"),
                "last_changed": e.get("last_changed"),
            }
            for e in entities
            if e.get("entity_id", "").startswith("camera.")
        ]
        return {"count": len(cameras), "cameras": cameras}

    async def get_camera_snapshot(self, camera_entity_id: str) -> dict[str, Any]:
        """Fetch a camera snapshot and return it with embedded image data.

        The ``_image`` key carries base64 JPEG bytes understood by vision-capable
        LLM providers (Anthropic, Gemini, OpenAI).  Providers that don't support
        vision simply ignore this key in the serialised JSON.
        """
        image_bytes = await self.ha.get_camera_image(camera_entity_id)
        if not image_bytes:
            logger.warning("camera_snapshot_unavailable", entity_id=camera_entity_id)
            return {
                "camera_entity_id": camera_entity_id,
                "image_available": False,
                "error": "Camera image unavailable — the camera may be offline or the entity ID is wrong.",
            }

        b64 = base64.b64encode(image_bytes).decode("ascii")
        logger.info(
            "camera_snapshot_fetched",
            entity_id=camera_entity_id,
            size_bytes=len(image_bytes),
        )
        return {
            "camera_entity_id": camera_entity_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "image_available": True,
            # The _image key is a convention: providers that support vision detect
            # it and convert it to the appropriate multimodal content block format.
            "_image": {
                "base64": b64,
                "media_type": "image/jpeg",
            },
        }
