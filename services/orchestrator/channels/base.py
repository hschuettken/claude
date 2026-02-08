"""Abstract communication channel.

Every channel (Telegram, future TTS/STT, Clawdbot) implements this
interface so the brain can send messages without knowing the transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Channel(ABC):
    """Abstract bidirectional communication channel."""

    @abstractmethod
    async def start(self) -> None:
        """Start receiving messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""

    @abstractmethod
    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a text message to a specific user/chat."""
