"""Telegram alerting with cooldown/deduplication.

Sends alerts via the Telegram Bot API.  Tracks recently sent alerts to
avoid spamming the same issue every check cycle.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("alerts")


class TelegramAlerter:
    """Sends Telegram alerts with per-issue cooldown."""

    def __init__(
        self,
        bot_token: str,
        chat_ids: list[int],
        cooldown_seconds: int = 1800,  # 30 minutes default
    ) -> None:
        self._token = bot_token
        self._chat_ids = chat_ids
        self._cooldown = cooldown_seconds
        # alert_key → last_sent_timestamp
        self._last_alert: dict[str, float] = {}
        # Track active issues for daily summary
        self._active_issues: dict[str, str] = {}
        self._alerts_sent_today: int = 0
        self._recoveries_sent_today: int = 0

    @property
    def available(self) -> bool:
        return bool(self._token and self._chat_ids)

    @property
    def active_issue_count(self) -> int:
        return len(self._active_issues)

    @property
    def active_issues(self) -> dict[str, str]:
        return dict(self._active_issues)

    async def send_alert(
        self,
        alert_key: str,
        message: str,
        severity: str = "warning",
    ) -> bool:
        """Send an alert if not in cooldown for this key.

        Returns True if the alert was actually sent.
        """
        now = time.time()
        last = self._last_alert.get(alert_key, 0)

        if now - last < self._cooldown:
            return False  # Still in cooldown

        self._last_alert[alert_key] = now
        self._active_issues[alert_key] = message
        self._alerts_sent_today += 1

        icon = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}.get(severity, "⚠️")
        full_message = f"{icon} *Health Monitor*\n\n{message}"

        return await self._send_to_all(full_message)

    async def send_recovery(self, alert_key: str, message: str) -> bool:
        """Send a recovery notification and clear cooldown."""
        if alert_key not in self._active_issues:
            return False  # Was never alerted, skip

        self._last_alert.pop(alert_key, None)
        self._active_issues.pop(alert_key, None)
        self._recoveries_sent_today += 1

        full_message = f"🟢 *Health Monitor*\n\n{message}"
        return await self._send_to_all(full_message)

    async def send_summary(self, summary_text: str) -> bool:
        """Send the daily summary (no cooldown)."""
        full_message = f"📊 *Daily Health Summary*\n\n{summary_text}"
        return await self._send_to_all(full_message)

    def reset_daily_counters(self) -> None:
        self._alerts_sent_today = 0
        self._recoveries_sent_today = 0

    def get_stats(self) -> dict[str, Any]:
        return {
            "alerts_sent_today": self._alerts_sent_today,
            "recoveries_sent_today": self._recoveries_sent_today,
            "active_issues": len(self._active_issues),
            "cooldown_entries": len(self._last_alert),
        }

    async def _send_to_all(self, text: str) -> bool:
        """Send a message to all configured chat IDs."""
        if not self.available:
            logger.warning("telegram_not_configured")
            return False

        success = True
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chat_id in self._chat_ids:
                try:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{self._token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                        },
                    )
                    if resp.status_code != 200:
                        logger.error(
                            "telegram_send_failed",
                            chat_id=chat_id,
                            status=resp.status_code,
                            body=resp.text[:200],
                        )
                        success = False
                    else:
                        logger.info("telegram_alert_sent", chat_id=chat_id)
                except Exception:
                    logger.exception("telegram_send_error", chat_id=chat_id)
                    success = False

        return success
