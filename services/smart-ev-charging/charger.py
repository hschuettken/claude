"""Wallbox control abstraction for the Amtron charger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.ha_client import HomeAssistantClient

import structlog

logger = structlog.get_logger()

# Amtron vehicle state codes (register 122)
VEHICLE_STATE_NO_VEHICLE = "1"      # A — No vehicle
VEHICLE_STATE_CONNECTED = "2"       # B — Vehicle connected (not charging)
VEHICLE_STATE_CHARGING = "3"        # C — Charging
VEHICLE_STATE_CHARGING_VENT = "4"   # D — Charging with ventilation
VEHICLE_STATE_ERROR = "5"           # E — Error


@dataclass
class WallboxState:
    """Current state of the wallbox."""

    vehicle_state_raw: str
    vehicle_connected: bool
    vehicle_charging: bool
    current_power_w: float
    session_energy_kwh: float

    @property
    def vehicle_state_text(self) -> str:
        mapping = {
            VEHICLE_STATE_NO_VEHICLE: "No vehicle",
            VEHICLE_STATE_CONNECTED: "Connected",
            VEHICLE_STATE_CHARGING: "Charging",
            VEHICLE_STATE_CHARGING_VENT: "Charging (vent)",
            VEHICLE_STATE_ERROR: "Error",
        }
        return mapping.get(self.vehicle_state_raw, "Unknown")


class WallboxController:
    """Controls the Amtron wallbox via Home Assistant entities."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        vehicle_state_entity: str,
        power_entity: str,
        energy_session_entity: str,
        hems_power_number: str,
    ) -> None:
        self._ha = ha
        self._vehicle_state_entity = vehicle_state_entity
        self._power_entity = power_entity
        self._energy_session_entity = energy_session_entity
        self._hems_power_number = hems_power_number
        self._last_set_power: int | None = None

    async def read_state(self) -> WallboxState:
        """Read current wallbox state from HA entities."""
        vehicle_raw = await self._get_state(self._vehicle_state_entity, "0")
        power = await self._get_float_state(self._power_entity)
        energy = await self._get_float_state(self._energy_session_entity)

        vehicle_connected = vehicle_raw in (
            VEHICLE_STATE_CONNECTED,
            VEHICLE_STATE_CHARGING,
            VEHICLE_STATE_CHARGING_VENT,
        )
        vehicle_charging = vehicle_raw in (
            VEHICLE_STATE_CHARGING,
            VEHICLE_STATE_CHARGING_VENT,
        )

        return WallboxState(
            vehicle_state_raw=vehicle_raw,
            vehicle_connected=vehicle_connected,
            vehicle_charging=vehicle_charging,
            current_power_w=power,
            session_energy_kwh=energy,
        )

    async def set_power_limit(self, power_w: int) -> None:
        """Set the HEMS power limit on the wallbox.

        The number entity has step=60, so values are rounded accordingly.
        Setting 0 effectively pauses charging.
        """
        power_w = max(0, round(power_w / 60) * 60)

        if self._last_set_power == power_w:
            return  # No change needed

        await self._ha.call_service("number", "set_value", {
            "entity_id": self._hems_power_number,
            "value": power_w,
        })
        self._last_set_power = power_w
        logger.info("wallbox_power_set", power_w=power_w)

    async def pause(self) -> None:
        """Pause charging (set power limit to 0)."""
        await self.set_power_limit(0)

    # --- internal helpers ---

    async def _get_state(self, entity_id: str, default: str = "unknown") -> str:
        try:
            result = await self._ha.get_state(entity_id)
            state = result.get("state", default)
            if state in ("unavailable", "unknown"):
                return default
            return state
        except Exception:
            logger.warning("entity_read_failed", entity_id=entity_id)
            return default

    async def _get_float_state(self, entity_id: str, default: float = 0.0) -> float:
        state_str = await self._get_state(entity_id, str(default))
        try:
            return float(state_str)
        except (ValueError, TypeError):
            return default
