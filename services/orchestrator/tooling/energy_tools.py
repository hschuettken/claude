"""Energy tool definitions and handlers (PV, grid, battery, prices, history)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from config import OrchestratorSettings

logger = get_logger("tooling.energy_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_home_energy_summary",
            "description": (
                "Get a comprehensive snapshot of the home's current energy state: "
                "PV production, grid power, battery, EV charging, house consumption, "
                "PV forecast, and energy prices."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pv_forecast",
            "description": (
                "Get the PV solar production forecast for today and tomorrow in kWh, "
                "including per-hour breakdown if available."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_energy_prices",
            "description": (
                "Get current energy prices: grid buy price, feed-in tariff, "
                "EPEX spot price if available, and oil heating cost."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_energy_history",
            "description": (
                "Query historical energy data from InfluxDB. Returns hourly averages "
                "for the specified sensor over a time range. Use for trends and analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "HA entity ID, e.g. sensor.inverter_pv_east_energy",
                    },
                    "range_start": {
                        "type": "string",
                        "description": "Flux duration like '-24h', '-7d', '-30d'",
                        "default": "-24h",
                    },
                    "window": {
                        "type": "string",
                        "description": "Aggregation window like '1h', '1d'",
                        "default": "1h",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
]


class EnergyTools:
    """Handlers for energy-related tools."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        influx: InfluxClient,
        settings: OrchestratorSettings,
    ) -> None:
        self.ha = ha
        self.influx = influx
        self.settings = settings
        self._tz = ZoneInfo(settings.timezone)

    async def _read_float(self, entity_id: str, default: float = 0.0) -> float:
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", str(default))
            if val in ("unavailable", "unknown"):
                return default
            return float(val)
        except Exception:
            return default

    async def get_home_energy_summary(self) -> dict[str, Any]:
        s = self.settings
        reads = await asyncio.gather(
            self._read_float(s.pv_power_entity),
            self._read_float(s.grid_power_entity),
            self._read_float(s.house_power_entity),
            self._read_float(s.battery_power_entity),
            self._read_float(s.battery_soc_entity),
            self._read_float(s.ev_power_entity),
            self._read_float(s.pv_forecast_today_entity),
            self._read_float(s.pv_forecast_today_remaining_entity),
            self._read_float(s.pv_forecast_tomorrow_entity),
            return_exceptions=True,
        )

        def val(i: int) -> float | str:
            r = reads[i]
            return round(r, 1) if isinstance(r, (int, float)) else "unavailable"

        now = datetime.now(self._tz)
        grid_w = val(1)
        grid_direction = "unknown"
        if isinstance(grid_w, (int, float)):
            grid_direction = "exporting" if grid_w > 0 else "importing"

        return {
            "timestamp": now.isoformat(),
            "pv_production_w": val(0),
            "grid_power_w": grid_w,
            "grid_direction": grid_direction,
            "house_consumption_w": val(2),
            "battery_power_w": val(3),
            "battery_note": "positive=charging, negative=discharging",
            "battery_soc_pct": val(4),
            "ev_charging_w": val(5),
            "pv_forecast_today_kwh": val(6),
            "pv_forecast_remaining_kwh": val(7),
            "pv_forecast_tomorrow_kwh": val(8),
            "grid_price_ct_kwh": s.grid_price_ct,
            "feed_in_ct_kwh": s.feed_in_tariff_ct,
        }

    async def get_pv_forecast(self) -> dict[str, Any]:
        s = self.settings
        entities = [
            s.pv_forecast_today_entity,
            s.pv_forecast_today_remaining_entity,
            s.pv_forecast_tomorrow_entity,
        ]
        results: dict[str, Any] = {}
        for entity in entities:
            try:
                state = await self.ha.get_state(entity)
                results[entity] = {
                    "value": state.get("state"),
                    "unit": state.get("attributes", {}).get("unit_of_measurement"),
                    "hourly": state.get("attributes", {}).get("hourly"),
                }
            except Exception:
                results[entity] = {"value": "unavailable"}
        return results

    async def get_energy_prices(self) -> dict[str, Any]:
        s = self.settings
        result: dict[str, Any] = {
            "grid_buy_ct_kwh": s.grid_price_ct,
            "feed_in_ct_kwh": s.feed_in_tariff_ct,
            "oil_heating_ct_kwh": s.oil_price_per_kwh_ct,
        }
        try:
            epex = await self.ha.get_state(s.epex_price_entity)
            result["epex_spot_ct_kwh"] = epex.get("state")
            result["epex_attributes"] = {
                k: v
                for k, v in epex.get("attributes", {}).items()
                if k in ("data", "unit_of_measurement")
            }
        except Exception:
            result["epex_spot_ct_kwh"] = "unavailable"
        return result

    async def query_energy_history(
        self,
        entity_id: str,
        range_start: str = "-24h",
        window: str = "1h",
    ) -> dict[str, Any]:
        records = await asyncio.to_thread(
            self.influx.query_mean,
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start=range_start,
            window=window,
        )
        simplified = [
            {
                "time": str(r.get("_time", "")),
                "value": round(r.get("_value", 0), 2) if r.get("_value") is not None else None,
            }
            for r in records
        ]
        return {
            "entity_id": entity_id,
            "range": range_start,
            "window": window,
            "record_count": len(simplified),
            "data": simplified[:100],
        }
