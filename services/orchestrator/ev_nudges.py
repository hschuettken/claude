"""ev_nudges — proactive Telegram nudges keyed off journal events + presence (S4.4).

Two triggers:

1. ``on_plan_journal`` (subject: ``energy.ev.decision.plan``):
   * Not-plugged-in pre-deadline + significant kWh-needed → nudge to plug in.

2. ``on_pv_hourly`` (subject: ``energy.pv.forecast.hourly``):
   * Big PV opportunity tomorrow → suggest battery-drain prep.

Nudges have per-trigger Redis cooldowns so we don't spam. Telegram delivery
is best-effort: this module simply *queues* nudges into Redis under
``ev_nudges:queued`` (a list); a future Telegram bridge picks them up.
This avoids a hard dependency on the Telegram bot and keeps the service
self-contained while the orchestrator is in headless mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.log import get_logger

logger = get_logger("ev_nudges")

REDIS_QUEUE_KEY = "ev_nudges:queued"
REDIS_COOLDOWN_KEY = "ev_nudge_cooldown:{name}"

# Cooldowns prevent the same nudge firing repeatedly while the trigger
# condition persists across multiple plan/forecast cycles.
COOLDOWN_NOT_PLUGGED_S = 4 * 3600
COOLDOWN_PV_OPPORTUNITY_S = 24 * 3600

# Trigger thresholds.
NOT_PLUGGED_KWH_THRESHOLD = 5.0
NOT_PLUGGED_SOC_THRESHOLD = 50.0
PV_OPPORTUNITY_TOMORROW_KWH = 25.0


class EVNudges:
    def __init__(self, redis_client: Any, ev_state: dict[str, Any]) -> None:
        self._redis = redis_client
        self._ev_state = ev_state

    async def _cooldown_active(self, name: str, seconds: int) -> bool:
        try:
            last = await self._redis.get(REDIS_COOLDOWN_KEY.format(name=name))
        except Exception:
            return False
        if not last:
            return False
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            return False
        return (datetime.now(timezone.utc) - last_dt).total_seconds() < seconds

    async def _set_cooldown(self, name: str) -> None:
        try:
            await self._redis.set(
                REDIS_COOLDOWN_KEY.format(name=name),
                datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            logger.warning("nudge_cooldown_set_failed", name=name, exc_info=True)

    async def _enqueue_nudge(self, kind: str, text: str) -> None:
        payload = json.dumps(
            {
                "kind": kind,
                "text": text,
                "issued_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        try:
            await self._redis.rpush(REDIS_QUEUE_KEY, payload)
            logger.info("ev_nudge_enqueued", kind=kind, length=len(text))
        except Exception:
            logger.warning("ev_nudge_enqueue_failed", kind=kind, exc_info=True)

    async def on_plan_journal(self, subject: str, payload: dict) -> None:
        """Inspect a plan_generated event and fire the not-plugged-in nudge."""
        try:
            inputs_raw = payload.get("inputs_json", "{}")
            try:
                inputs = (
                    json.loads(inputs_raw)
                    if isinstance(inputs_raw, str)
                    else inputs_raw or {}
                )
            except (TypeError, json.JSONDecodeError):
                inputs = {}

            plugged = bool(inputs.get("vehicle_plugged_in", False))
            try:
                energy_needed = float(payload.get("energy_needed_kwh", 0.0) or 0.0)
            except (TypeError, ValueError):
                energy_needed = 0.0
            try:
                current_soc = float(payload.get("current_soc_pct", 100.0) or 100.0)
            except (TypeError, ValueError):
                current_soc = 100.0

            if (
                not plugged
                and energy_needed > NOT_PLUGGED_KWH_THRESHOLD
                and current_soc < NOT_PLUGGED_SOC_THRESHOLD
            ):
                if await self._cooldown_active("not_plugged", COOLDOWN_NOT_PLUGGED_S):
                    return
                text = (
                    f"🔌 EV not plugged in. Tomorrow needs {energy_needed:.1f} kWh, "
                    f"you're at {current_soc:.0f}%. Plug in by 23:00 for Eco overnight."
                )
                await self._enqueue_nudge(kind="not_plugged", text=text)
                await self._set_cooldown("not_plugged")
        except Exception:
            logger.exception("nudge_plan_journal_failed")

    async def on_pv_hourly(self, subject: str, payload: dict) -> None:
        """Fire the big-PV-opportunity nudge for tomorrow's window."""
        try:
            slots = payload.get("hourly", []) or []
            tomorrow_kwh = self._sum_tomorrow_kwh(slots)
            if tomorrow_kwh <= PV_OPPORTUNITY_TOMORROW_KWH:
                return
            if await self._cooldown_active("pv_opportunity", COOLDOWN_PV_OPPORTUNITY_S):
                return
            text = (
                f"☀️ Tomorrow's PV looks great ({tomorrow_kwh:.0f} kWh forecast). "
                f"Draining home battery now to clear room — EV will harvest most of it."
            )
            await self._enqueue_nudge(kind="pv_opportunity", text=text)
            await self._set_cooldown("pv_opportunity")
        except Exception:
            logger.exception("nudge_pv_failed")

    @staticmethod
    def _sum_tomorrow_kwh(slots: list[dict]) -> float:
        """Sum kWh across the slot range that falls on tomorrow's date (UTC)."""
        if not slots:
            return 0.0
        try:
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        except Exception:
            return 0.0
        total = 0.0
        for slot in slots:
            time_iso = slot.get("time_iso")
            if not time_iso:
                continue
            try:
                t = datetime.fromisoformat(str(time_iso).replace("Z", "+00:00"))
            except ValueError:
                continue
            if t.date() == tomorrow:
                try:
                    total += float(slot.get("kwh", 0.0))
                except (TypeError, ValueError):
                    continue
        return total
