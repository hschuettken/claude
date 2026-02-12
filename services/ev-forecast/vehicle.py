"""Combined HA template sensor vehicle monitoring.

Monitors the Audi A6 e-tron through combined Home Assistant template sensors
that merge data from dual Audi Connect accounts (Henning & Nicole). HA determines
which account has valid data (the person who last drove); this module simply reads
the resulting combined sensors. Cloud data refresh still iterates VINs directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import structlog

from shared.ha_client import HomeAssistantClient

logger = structlog.get_logger()


@dataclass
class VehicleState:
    """Current state of the EV from Audi Connect."""

    soc_pct: float | None = None            # State of charge (0-100)
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
class VehicleConfig:
    """Entity IDs for the combined HA template sensors.

    These sensors merge data from both Audi Connect accounts. HA picks
    the active account automatically (e.g. via mileage comparison).
    """

    soc_entity: str
    range_entity: str
    charging_entity: str
    plug_entity: str
    mileage_entity: str
    remaining_charge_entity: str
    active_account_entity: str


@dataclass
class RefreshConfig:
    """Configuration for one Audi Connect cloud refresh target."""

    name: str
    vin: str


class VehicleMonitor:
    """Monitors the EV via combined HA template sensors.

    Reads vehicle state from a single set of combined sensors that HA
    maintains by merging data from Henning's and Nicole's Audi Connect
    accounts. Cloud data refresh still triggers both VINs since either
    account may need updating.
    """

    def __init__(
        self,
        ha: HomeAssistantClient,
        vehicle_config: VehicleConfig,
        refresh_configs: list[RefreshConfig],
        net_capacity_kwh: float = 76.0,
        stale_threshold_minutes: int = 60,
    ) -> None:
        self._ha = ha
        self._vehicle_config = vehicle_config
        self._refresh_configs = refresh_configs
        self._net_capacity_kwh = net_capacity_kwh
        self._stale_threshold_min = stale_threshold_minutes
        self._last_state: VehicleState = VehicleState()
        self._last_refresh: datetime | None = None

    @property
    def last_state(self) -> VehicleState:
        return self._last_state

    async def read_state(self) -> VehicleState:
        """Read vehicle state from the combined HA template sensors.

        Reads all sensor values in one pass. If the combined sensors return
        valid data (at least SoC), updates and returns the new state.
        Otherwise returns the last known good state.
        """
        cfg = self._vehicle_config

        soc = await self._read_float(cfg.soc_entity)
        range_km = await self._read_float(cfg.range_entity)
        charging = await self._read_str(cfg.charging_entity)
        plug = await self._read_str(cfg.plug_entity)
        mileage = await self._read_float(cfg.mileage_entity)
        remaining = await self._read_float(cfg.remaining_charge_entity)
        active_account = await self._read_str(cfg.active_account_entity)

        state = VehicleState(
            soc_pct=soc,
            range_km=range_km,
            charging_state=charging,
            plug_state=plug,
            mileage_km=mileage,
            remaining_charge_min=remaining,
            active_account=active_account,
            last_updated=datetime.now() if soc is not None else None,
        )

        if state.is_valid:
            self._last_state = state
            logger.info(
                "vehicle_state_read",
                account=state.active_account,
                soc=state.soc_pct,
                range_km=state.range_km,
                charging=state.charging_state,
                plug=state.plug_state,
            )
        else:
            logger.warning(
                "vehicle_state_invalid",
                last_soc=self._last_state.soc_pct,
            )

        return self._last_state

    async def refresh_data(self) -> bool:
        """Trigger a cloud data refresh via the Audi Connect HA script.

        Calls the ev_refresh_cloud script which refreshes cloud data for
        all registered accounts in one API call. Then re-reads state.
        Returns True if fresh data was obtained.
        """
        refreshed = False
        try:
            await self._ha.call_service("script", "ev_refresh_cloud", {})
            logger.info("cloud_refresh_triggered")
            refreshed = True
        except Exception:
            logger.debug("cloud_refresh_failed")

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
