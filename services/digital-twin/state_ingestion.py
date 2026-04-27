"""State ingestion from Home Assistant REST API and InfluxDB.

Pulls the current EnergyState and per-room RoomState from HA and
stores a snapshot in the DB for the simulation engine to consume.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import settings
from .models import EnergyState, HouseState, RoomState
from . import room_registry

logger = logging.getLogger(__name__)


class HAStateIngester:
    """Pull current states from Home Assistant REST API."""

    def __init__(
        self,
        ha_url: str = "",
        ha_token: str = "",
    ) -> None:
        self._url = ha_url or settings.ha_url
        self._token = ha_token or settings.ha_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _get_state(
        self, client: httpx.AsyncClient, entity_id: str
    ) -> Optional[str]:
        """Fetch the raw state string for a single entity."""
        try:
            resp = await client.get(
                f"{self._url}/api/states/{entity_id}",
                headers=self._headers,
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json().get("state")
            logger.debug("ha_state_miss entity=%s status=%d", entity_id, resp.status_code)
        except Exception as exc:
            logger.debug("ha_state_error entity=%s error=%s", entity_id, exc)
        return None

    def _parse_float(self, value: Optional[str], default: float = 0.0) -> float:
        if value is None or value in ("unavailable", "unknown", ""):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _parse_bool(self, value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        return value.lower() in ("on", "true", "home", "detected", "active", "occupied")

    async def fetch_energy_state(self) -> EnergyState:
        """Fetch current energy readings from HA."""
        async with httpx.AsyncClient() as client:
            pv_east = await self._get_state(client, settings.ha_entity_pv_east_power)
            pv_west = await self._get_state(client, settings.ha_entity_pv_west_power)
            batt_soc = await self._get_state(client, settings.ha_entity_battery_soc)
            batt_power = await self._get_state(client, settings.ha_entity_battery_power)
            grid = await self._get_state(client, settings.ha_entity_grid_power)
            house = await self._get_state(client, settings.ha_entity_house_consumption)
            ev_power = await self._get_state(client, settings.ha_entity_ev_power)
            ev_soc = await self._get_state(client, settings.ha_entity_ev_soc)

        pv_east_w = self._parse_float(pv_east)
        pv_west_w = self._parse_float(pv_west)
        return EnergyState(
            timestamp=datetime.now(timezone.utc),
            pv_east_power_w=pv_east_w,
            pv_west_power_w=pv_west_w,
            pv_total_power_w=pv_east_w + pv_west_w,
            battery_soc_pct=self._parse_float(batt_soc),
            battery_power_w=self._parse_float(batt_power),
            grid_power_w=self._parse_float(grid),
            house_consumption_w=self._parse_float(house),
            ev_charging_w=self._parse_float(ev_power),
            ev_soc_pct=self._parse_float(ev_soc) if ev_soc else None,
        )

    async def fetch_room_states(self) -> dict[str, RoomState]:
        """Fetch temperature / humidity / occupancy for all registered rooms."""
        rooms = await room_registry.list_rooms()
        room_states: dict[str, RoomState] = {}

        async with httpx.AsyncClient() as client:
            for room in rooms:
                temperature: Optional[float] = None
                humidity: Optional[float] = None
                occupancy: Optional[bool] = None
                heating_on: Optional[bool] = None
                entities: list[str] = list(room.extra_entities)

                if room.ha_temperature_entity:
                    val = await self._get_state(client, room.ha_temperature_entity)
                    temperature = self._parse_float(val) if val else None
                    entities.append(room.ha_temperature_entity)

                if room.ha_humidity_entity:
                    val = await self._get_state(client, room.ha_humidity_entity)
                    humidity = self._parse_float(val) if val else None
                    entities.append(room.ha_humidity_entity)

                if room.ha_occupancy_entity:
                    val = await self._get_state(client, room.ha_occupancy_entity)
                    occupancy = self._parse_bool(val)
                    entities.append(room.ha_occupancy_entity)

                if room.ha_heating_entity:
                    val = await self._get_state(client, room.ha_heating_entity)
                    heating_on = val not in ("off", "idle", None)
                    entities.append(room.ha_heating_entity)

                room_states[room.room_id] = RoomState(
                    room_id=room.room_id,
                    name=room.name,
                    temperature_c=temperature,
                    humidity_pct=humidity,
                    occupancy=occupancy,
                    heating_on=heating_on,
                    entities=list(set(entities)),
                )

        return room_states

    async def fetch_house_state(self) -> HouseState:
        """Build full HouseState from HA."""
        energy = await self.fetch_energy_state()
        rooms = await self.fetch_room_states()
        return HouseState(
            timestamp=energy.timestamp,
            energy=energy,
            rooms=rooms,
            data_source="ha",
        )


class PVForecastIngester:
    """Ingest PV forecast for simulation (24h horizon).

    Tries HA sensor entities first (Forecast.Solar integration), then falls
    back to a sine-curve approximation based on current production.
    """

    FORECAST_EAST_ENTITY = "sensor.energy_production_today_east"
    FORECAST_WEST_ENTITY = "sensor.energy_production_today_west"

    def __init__(self, ha_url: str = "", ha_token: str = "") -> None:
        self._url = ha_url or settings.ha_url
        self._token = ha_token or settings.ha_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def fetch_24h_kwh(
        self,
        current_pv_w: float = 0.0,
    ) -> list[float]:
        """Return 24 hourly PV production estimates (kWh)."""
        try:
            async with httpx.AsyncClient() as client:
                east_resp = await client.get(
                    f"{self._url}/api/states/{self.FORECAST_EAST_ENTITY}",
                    headers=self._headers,
                    timeout=5,
                )
                west_resp = await client.get(
                    f"{self._url}/api/states/{self.FORECAST_WEST_ENTITY}",
                    headers=self._headers,
                    timeout=5,
                )
                total_kwh = 0.0
                for r in (east_resp, west_resp):
                    if r.status_code == 200:
                        v = r.json().get("state", "0")
                        try:
                            total_kwh += float(v)
                        except (ValueError, TypeError):
                            pass
                if total_kwh > 0:
                    return _shape_forecast(total_kwh)
        except Exception as exc:
            logger.debug("pv_forecast_ha_failed error=%s", exc)

        # Fallback: estimate from current production
        estimated_daily = max(current_pv_w / 1000 * 6, 1.0)
        return _shape_forecast(estimated_daily)


def _shape_forecast(daily_kwh: float) -> list[float]:
    """Distribute daily_kwh across 24 hours using a daylight profile.

    Peak production is between hours 9-16 (UTC) following a bell curve.
    """
    import math

    # Fraction of daily production per hour (sums to 1.0)
    profile = [
        0.000, 0.000, 0.000, 0.000, 0.000, 0.005,  # 0-5
        0.020, 0.040, 0.075, 0.105, 0.125, 0.130,  # 6-11
        0.130, 0.125, 0.105, 0.075, 0.040, 0.015,  # 12-17
        0.007, 0.003, 0.000, 0.000, 0.000, 0.000,  # 18-23
    ]
    assert abs(sum(profile) - 1.0) < 0.01, f"profile must sum to 1, got {sum(profile)}"
    return [round(daily_kwh * p, 4) for p in profile]
