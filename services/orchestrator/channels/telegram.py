"""Telegram communication channel.

Uses ``python-telegram-bot`` v20+ (fully async).  Provides:
- Free-text messages → routed to the Brain for LLM processing
- /start, /status, /forecast, /clear — quick-access commands
- Outbound notifications (proactive alerts, briefings)

Only messages from allowed chat IDs are processed (security).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from shared.log import get_logger

from channels.base import Channel

if TYPE_CHECKING:
    from brain import Brain
    from config import OrchestratorSettings
    from telegram.ext import ContextTypes

logger = get_logger("telegram")

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096


class TelegramChannel(Channel):
    """Telegram bot channel for the orchestrator."""

    def __init__(
        self,
        settings: OrchestratorSettings,
        brain: Brain,
    ) -> None:
        self._settings = settings
        self._brain = brain
        self._allowed_ids = set(settings.allowed_chat_ids)

        self._app: Application | None = None
        if settings.telegram_bot_token:
            self._app = (
                Application.builder()
                .token(settings.telegram_bot_token)
                .build()
            )
            self._register_handlers()
        else:
            logger.warning("telegram_disabled", reason="No TELEGRAM_BOT_TOKEN configured")

    def _register_handlers(self) -> None:
        assert self._app is not None
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("forecast", self._cmd_forecast))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("whoami", self._cmd_whoami))
        # Free text — must be last
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._on_message,
        ))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._app:
            return
        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("telegram_started", allowed_chats=list(self._allowed_ids))

    async def stop(self) -> None:
        if not self._app:
            return
        if self._app.updater:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        logger.info("telegram_stopped")

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a message to a specific chat (for proactive notifications)."""
        if not self._app:
            logger.warning("telegram_not_configured")
            return
        # Split long messages
        for chunk in self._split_message(text):
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                # Markdown parse error — retry as plain text
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                )

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    def _is_allowed(self, update: Update) -> bool:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._allowed_ids:
            # If no IDs configured, allow all (first-time setup convenience)
            logger.warning("no_chat_id_filter", chat_id=chat_id)
            return True
        return chat_id in self._allowed_ids

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name if update.effective_user else ""
        await update.message.reply_text(
            f"Hi {user_name}! I'm your home orchestrator.\n\n"
            f"Ask me anything about your home — energy, PV forecast, EV charging, "
            f"heating, or just chat.\n\n"
            f"Commands:\n"
            f"/status — Current home energy snapshot\n"
            f"/forecast — PV forecast for today & tomorrow\n"
            f"/clear — Clear conversation history\n"
            f"/whoami — Show your chat ID\n"
            f"/help — This message\n\n"
            f"Your chat ID: `{chat_id}` (add to TELEGRAM_ALLOWED_CHAT_IDS)",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        await self._cmd_start(update, context)

    async def _cmd_whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show chat ID — useful during first-time setup."""
        chat_id = update.effective_chat.id
        await update.message.reply_text(
            f"Your chat ID: `{chat_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        response = await self._brain.process_message(
            "Give me a brief current energy status of the house. "
            "Include PV production, grid, battery, EV, and house consumption.",
            chat_id=str(update.effective_chat.id),
            user_name=update.effective_user.first_name if update.effective_user else "",
        )
        await self._reply(update, response)

    async def _cmd_forecast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        response = await self._brain.process_message(
            "Show me the PV solar forecast for today and tomorrow. "
            "Include total kWh and any notable hours.",
            chat_id=str(update.effective_chat.id),
            user_name=update.effective_user.first_name if update.effective_user else "",
        )
        await self._reply(update, response)

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        from memory import Memory
        memory = Memory()
        memory.clear_history(str(update.effective_chat.id))
        await update.message.reply_text("Conversation history cleared.")

    # ------------------------------------------------------------------
    # Free-text message handler
    # ------------------------------------------------------------------

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        if not update.message or not update.message.text:
            return

        chat_id = str(update.effective_chat.id)
        user_name = update.effective_user.first_name if update.effective_user else ""
        user_text = update.message.text

        logger.info("telegram_message", chat_id=chat_id, user=user_name, length=len(user_text))

        # Show typing indicator
        await update.effective_chat.send_action(ChatAction.TYPING)

        response = await self._brain.process_message(
            user_text,
            chat_id=chat_id,
            user_name=user_name,
        )

        await self._reply(update, response)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _reply(self, update: Update, text: str) -> None:
        """Reply to a message, splitting if too long. Falls back to plain text."""
        for chunk in self._split_message(text):
            try:
                await update.message.reply_text(
                    chunk, parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                # Markdown parse error — retry as plain text
                await update.message.reply_text(chunk)

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """Split long messages at paragraph boundaries."""
        if len(text) <= MAX_MESSAGE_LENGTH:
            return [text]

        chunks: list[str] = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        return chunks or [text[:MAX_MESSAGE_LENGTH]]
