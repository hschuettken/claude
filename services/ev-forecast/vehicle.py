"""Vehicle monitoring via Home Assistant sensors (Audi Connect).

Monitors the Audi A6 e-tron through Home Assistant sensors, either:
- Single account (direct Audi Connect entities) — recommended
- Dual account (combined HA template sensors merging two accounts)

Also includes a ConsumptionTracker that calculates actual kWh/100km
dynamically from mileage and SoC changes, replacing the fixed default
with real driving data as it accumulates.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
            "connected", "locked", "angeschlossen", "on",
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
    """Entity IDs for the HA sensors.

    In single-account mode, these are direct Audi Connect entities.
    In dual-account mode, these are combined HA template sensors
    that merge data from both accounts.
    """

    soc_entity: str
    range_entity: str
    charging_entity: str
    plug_entity: str
    mileage_entity: str
    remaining_charge_entity: str
    active_account_entity: str  # Empty in single-account mode


@dataclass
class RefreshConfig:
    """Configuration for one Audi Connect cloud refresh target."""

    name: str
    vin: str


# ------------------------------------------------------------------
# Consumption Tracker
# ------------------------------------------------------------------


class ConsumptionTracker:
    """Calculates actual EV consumption (kWh/100km) from mileage and SoC.

    Monitors consecutive vehicle readings. When a driving segment is
    detected (mileage increases while SoC decreases), the actual energy
    consumption is calculated and added to a rolling history.

    Over time, this replaces the fixed default with real-world data
    that adapts to driving style, temperature, highway vs city, etc.
    """

    def __init__(
        self,
        battery_capacity_kwh: float = 83.0,
        default_consumption: float = 22.0,
        max_history: int = 50,
        min_plausible_consumption: float = 18.0,
        max_plausible_consumption: float = 35.0,
    ) -> None:
        self._capacity = battery_capacity_kwh
        self._default = default_consumption
        self._max_history = max_history
        self._min_plausible = min_plausible_consumption
        self._max_plausible = max_plausible_consumption
        # Rolling list of measured consumption values (kWh/100km)
        self._history: list[float] = []
        # Last reading for comparison
        self._last_mileage: float | None = None
        self._last_soc: float | None = None

    def update(self, mileage_km: float | None, soc_pct: float | None) -> float | None:
        """Record a new reading. Returns consumption if a driving segment was detected.

        A driving segment is detected when mileage increased AND SoC decreased
        compared to the previous reading. The consumption is only recorded if
        it falls within a sane range (5–60 kWh/100km).
        """
        if mileage_km is None or soc_pct is None:
            return None

        result = None

        if self._last_mileage is not None and self._last_soc is not None:
            km_delta = mileage_km - self._last_mileage
            soc_delta = self._last_soc - soc_pct  # Positive when driving (SoC drops)

            # Driving segment: mileage went up AND SoC went down
            if km_delta > 1.0 and soc_delta > 0.5:
                energy_used = soc_delta / 100.0 * self._capacity
                consumption = energy_used / km_delta * 100.0

                # Sanity check: reasonable range for an EV
                if 5.0 <= consumption <= 60.0:
                    self._history.append(round(consumption, 1))
                    if len(self._history) > self._max_history:
                        self._history = self._history[-self._max_history:]
                    result = consumption
                    logger.info(
                        "consumption_measured",
                        km_delta=round(km_delta, 1),
                        soc_delta=round(soc_delta, 1),
                        energy_kwh=round(energy_used, 1),
                        consumption_kwh_100km=round(consumption, 1),
                        rolling_avg=self.consumption_kwh_per_100km,
                    )
                else:
                    logger.debug(
                        "consumption_out_of_range",
                        km_delta=round(km_delta, 1),
                        soc_delta=round(soc_delta, 1),
                        consumption=round(consumption, 1),
                    )

        self._last_mileage = mileage_km
        self._last_soc = soc_pct
        return result

    @property
    def consumption_kwh_per_100km(self) -> float:
        """Current consumption estimate.

        Uses weighted rolling average favoring recent measurements (seasonal adaptation).
        Blends with default for low sample counts, bounded to plausible range.
        Recent samples weighted more heavily to adapt to seasonal changes (winter/summer).
        """
        if not self._history:
            base = self._default
        else:
            # Use last 20 samples for rolling average, but weight recent ones more
            recent = self._history[-20:]
            n = len(recent)
            
            if n <= 3:
                # Very few samples: blend heavily with default
                measured_avg = sum(recent) / n
                weight_measured = 0.3 * n  # 30% weight per sample, max 90%
                base = (measured_avg * weight_measured) + (self._default * (1.0 - weight_measured))
            else:
                # Enough samples: use weighted average favoring recent data
                # Weight decay: most recent = 1.0, each older sample gets 0.95x weight
                weights = [0.95 ** i for i in range(n)]
                weights.reverse()  # Most recent gets highest weight
                weighted_sum = sum(val * w for val, w in zip(recent, weights))
                weight_sum = sum(weights)
                measured_avg = weighted_sum / weight_sum
                
                # Reduce default influence as we get more data
                weight_measured = min(1.0, n / 10.0)  # Full trust after 10 samples
                base = (measured_avg * weight_measured) + (self._default * (1.0 - weight_measured))

        return round(max(self._min_plausible, min(self._max_plausible, base)), 1)

    @property
    def has_data(self) -> bool:
        """True if at least one real measurement exists."""
        return len(self._history) > 0

    @property
    def measurement_count(self) -> int:
        return len(self._history)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for state persistence."""
        return {
            "history": self._history,
            "last_mileage": self._last_mileage,
            "last_soc": self._last_soc,
            "current_estimate": self.consumption_kwh_per_100km,
            "default": self._default,
            "measurement_count": len(self._history),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        capacity: float,
        default: float,
        min_plausible: float = 18.0,
        max_plausible: float = 35.0,
    ) -> ConsumptionTracker:
        """Restore from persisted state."""
        tracker = cls(capacity, default, min_plausible_consumption=min_plausible, max_plausible_consumption=max_plausible)
        tracker._history = data.get("history", [])
        tracker._last_mileage = data.get("last_mileage")
        tracker._last_soc = data.get("last_soc")
        return tracker


# ------------------------------------------------------------------
# Vehicle Monitor
# ------------------------------------------------------------------


class VehicleMonitor:
    """Monitors the EV via HA sensors.

    Supports both single-account mode (direct Audi Connect entities)
    and dual-account mode (combined HA template sensors). Cloud data
    refresh is triggered via HA scripts.
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
        """Read vehicle state from HA sensors."""
        cfg = self._vehicle_config

        soc = await self._read_float(cfg.soc_entity)
        range_km = await self._read_float(cfg.range_entity)
        charging = await self._read_str(cfg.charging_entity)
        plug = await self._read_str(cfg.plug_entity)
        mileage = await self._read_float(cfg.mileage_entity)
        remaining = await self._read_float(cfg.remaining_charge_entity)

        # Active account: only read if entity is configured (dual-account mode)
        active_account = ""
        if cfg.active_account_entity:
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
                soc=state.soc_pct,
                range_km=state.range_km,
                charging=state.charging_state,
                plug=state.plug_state,
                mileage=state.mileage_km,
                account=state.active_account or "single",
            )
        else:
            logger.warning(
                "vehicle_state_invalid",
                last_soc=self._last_state.soc_pct,
            )

        return self._last_state

    async def refresh_data(self) -> bool:
        """Trigger a cloud data refresh via the Audi Connect HA script."""
        refreshed = False
        try:
            await self._ha.call_service("script", "ev_refresh_cloud", {})
            logger.info("cloud_refresh_triggered")
            refreshed = True
        except Exception:
            logger.debug("cloud_refresh_failed")

        if refreshed:
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
        if self._last_refresh is None:
            return True
        age_min = (datetime.now() - self._last_refresh).total_seconds() / 60
        return age_min > self._stale_threshold_min

    async def _read_float(self, entity_id: str) -> float | None:
        if not entity_id:
            return None
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
        if not entity_id:
            return "unknown"
        try:
            state = await self._ha.get_state(entity_id)
            val = state.get("state", "unknown")
            if val in ("unavailable", "unknown", "none", "None", ""):
                return "unknown"
            return val
        except Exception:
            return "unknown"
