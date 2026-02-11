"""Dual Audi Connect account handling.

Monitors the Audi A6 e-tron through two Audi Connect accounts (Hans & Nicole).
Only the person who last drove the car can see valid data in their account —
the other shows "unknown". This module tries both accounts and picks the one
with valid data, refreshing via HA service calls when needed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from shared.ha_client import HomeAssistantClient

logger = structlog.get_logger()


@dataclass
class VehicleState:
    """Current state of the EV from Audi Connect."""

    soc_pct: float | None = None            # State of charge (0–100)
    range_km: float | None = None            # Electric range in km
    charging_state: str = "unknown"          # Charging / Not charging / etc.
    plug_state: str = "unknown"              # Connected / Disconnected
    mileage_km: float | None = None          # Total mileage
    remaining_charge_min: float | None = None # Minutes until full
    active_account: str = ""                 # Which account provided valid data
    last_updated: datetime | None = None

    @property
    def is_valid(self) -> bool:
        """True if we have at least SoC data."""
        return self.soc_pct is not None

    @property
    def is_charging(self) -> bool:
        return self.charging_state.lower() in ("charging", "laden")

    @property
    def is_plugged_in(self) -> bool:
        return self.plug_state.lower() in (
            "connected", "locked", "angeschlossen",
        )

    @property
    def energy_kwh(self) -> float | None:
        """Estimated energy in battery (kWh) from SoC."""
        if self.soc_pct is None:
            return None
        # Using net capacity for usable energy
        return self.soc_pct / 100.0 * 76.0  # Will be overridden with config value


@dataclass
class AccountConfig:
    """Configuration for one Audi Connect account."""

    name: str
    soc_entity: str
    range_entity: str
    charging_entity: str
    plug_entity: str
    mileage_entity: str
    remaining_charge_entity: str
    vin: str


class VehicleMonitor:
    """Monitors the EV via dual Audi Connect accounts in Home Assistant."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        account1: AccountConfig,
        account2: AccountConfig,
        net_capacity_kwh: float = 76.0,
        stale_threshold_minutes: int = 60,
    ) -> None:
        self._ha = ha
        self._accounts = [account1, account2]
        self._net_capacity_kwh = net_capacity_kwh
        self._stale_threshold_min = stale_threshold_minutes
        self._active_account_idx: int | None = None
        self._last_state: VehicleState = VehicleState()
        self._last_refresh: datetime | None = None

    @property
    def last_state(self) -> VehicleState:
        return self._last_state

    async def read_state(self) -> VehicleState:
        """Read vehicle state, trying both accounts.

        Strategy:
        1. Try the last known active account first
        2. If it returns "unknown", try the other account
        3. If both fail, return the last known good state
        """
        # Try accounts in priority order (last active first)
        order = self._get_account_order()

        for idx in order:
            account = self._accounts[idx]
            state = await self._read_account(account)
            if state.is_valid:
                state.active_account = account.name
                state.last_updated = datetime.now()
                self._active_account_idx = idx
                self._last_state = state
                logger.info(
                    "vehicle_state_read",
                    account=account.name,
                    soc=state.soc_pct,
                    range_km=state.range_km,
                    charging=state.charging_state,
                    plug=state.plug_state,
                )
                return state
            else:
                logger.debug(
                    "account_returned_unknown",
                    account=account.name,
                )

        # Both accounts failed — return last known state
        logger.warning("both_accounts_unknown", last_soc=self._last_state.soc_pct)
        return self._last_state

    async def refresh_data(self) -> bool:
        """Trigger a cloud data refresh via the Audi Connect service.

        Tries both accounts' refresh_cloud_data service and then reads state.
        Returns True if fresh data was obtained.
        """
        refreshed = False
        for account in self._accounts:
            if account.vin:
                try:
                    await self._ha.call_service(
                        "audiconnect",
                        "refresh_cloud_data",
                        {"vin": account.vin},
                    )
                    logger.info("cloud_refresh_triggered", account=account.name)
                    refreshed = True
                except Exception:
                    logger.debug("cloud_refresh_failed", account=account.name)

        if refreshed:
            # Wait a moment for data to propagate
            await asyncio.sleep(10)
            await self.read_state()

        self._last_refresh = datetime.now()
        return self._last_state.is_valid

    async def ensure_fresh_data(self) -> VehicleState:
        """Read state, trigger refresh if stale."""
        state = await self.read_state()

        if not state.is_valid or self._is_stale():
            logger.info("data_stale_or_invalid, refreshing")
            await self.refresh_data()
            state = await self.read_state()

        return state

    def _is_stale(self) -> bool:
        """Check if the last refresh was too long ago."""
        if self._last_refresh is None:
            return True
        age_min = (datetime.now() - self._last_refresh).total_seconds() / 60
        return age_min > self._stale_threshold_min

    def _get_account_order(self) -> list[int]:
        """Return account indices, active one first."""
        if self._active_account_idx is not None:
            other = 1 - self._active_account_idx
            return [self._active_account_idx, other]
        return [0, 1]

    async def _read_account(self, account: AccountConfig) -> VehicleState:
        """Read vehicle state from one account's entities."""
        soc = await self._read_float(account.soc_entity)
        range_km = await self._read_float(account.range_entity)
        charging = await self._read_str(account.charging_entity)
        plug = await self._read_str(account.plug_entity)
        mileage = await self._read_float(account.mileage_entity)
        remaining = await self._read_float(account.remaining_charge_entity)

        return VehicleState(
            soc_pct=soc,
            range_km=range_km,
            charging_state=charging,
            plug_state=plug,
            mileage_km=mileage,
            remaining_charge_min=remaining,
        )

    async def _read_float(self, entity_id: str) -> float | None:
        """Read a float sensor value, returning None for unknown/unavailable."""
        try:
            state = await self._ha.get_state(entity_id)
            val = state.get("state", "unknown")
            if val in ("unavailable", "unknown", "none", "None", ""):
                return None
            return float(val)
        except (ValueError, TypeError):
            return None
        except Exception:
            logger.debug("entity_read_failed", entity_id=entity_id)
            return None

    async def _read_str(self, entity_id: str) -> str:
        """Read a string sensor value."""
        try:
            state = await self._ha.get_state(entity_id)
            val = state.get("state", "unknown")
            if val in ("unavailable", "unknown", "none", "None", ""):
                return "unknown"
            return val
        except Exception:
            return "unknown"
