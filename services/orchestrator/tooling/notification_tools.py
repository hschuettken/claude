"""Notification tool definitions and handlers."""

from __future__ import annotations

from typing import Any

from shared.log import get_logger

logger = get_logger("tooling.notification_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": (
                "Send a Telegram notification to a specific user by chat ID. "
                "Use this for proactive alerts or forwarding info to another household member."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "Telegram chat ID of the recipient",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text to send",
                    },
                },
                "required": ["chat_id", "message"],
            },
        },
    },
]


class NotificationTools:
    """Handlers for notification tools."""

    def __init__(self, send_notification_fn: Any = None) -> None:
        self._send_notification = send_notification_fn

    async def send_notification(
        self, chat_id: str, message: str
    ) -> dict[str, Any]:
        if self._send_notification:
            await self._send_notification(int(chat_id), message)
            return {"success": True, "chat_id": chat_id}
        return {"error": "Notification channel not available"}
