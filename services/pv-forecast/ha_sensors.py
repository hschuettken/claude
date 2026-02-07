"""Publish forecast results to Home Assistant as sensors.

Creates/updates sensors via the HA REST API (POST /api/states/sensor.xxx).
These sensors appear in HA like any other entity and get recorded to InfluxDB
automatically if the user has the InfluxDB integration configured.

Sensors created:
    {prefix}_today_kwh              Total forecast for today (both arrays)
    {prefix}_today_remaining_kwh    Remaining today from current hour
    {prefix}_tomorrow_kwh           Total forecast for tomorrow
    {prefix}_day_after_tomorrow_kwh Total forecast for day after tomorrow
    {prefix}_east_today_kwh         East array today
    {prefix}_east_tomorrow_kwh      East array tomorrow
    {prefix}_west_today_kwh         West array today
    {prefix}_west_tomorrow_kwh      West array tomorrow

Each sensor includes an "hourly" attribute with per-hour breakdown and
metadata about the model type used (ml/fallback).

Also publishes solar radiation forecast as a sensor for historical tracking.
"""

from __future__ import annotations

from typing import Any

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger

from forecast import ArrayForecast, DayForecast, FullForecast

logger = get_logger("ha-sensors")


def _hourly_attr(day: DayForecast | None) -> list[dict[str, Any]]:
    """Format hourly breakdown for HA sensor attributes."""
    if not day or not day.hourly:
        return []
    return [
        {"hour": h.time.strftime("%H:%M"), "kwh": h.kwh}
        for h in day.hourly
    ]


def _array_attrs(arr: ArrayForecast | None, day_key: str) -> dict[str, Any]:
    """Build attributes for an array/day sensor."""
    if arr is None:
        return {"model_type": "none"}
    day: DayForecast | None = getattr(arr, day_key, None)
    return {
        "model_type": arr.model_type,
        "hourly": _hourly_attr(day),
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total",
        "friendly_name_suffix": f"{arr.array_name} {day_key}",
    }


class HASensorPublisher:
    """Publishes PV forecast data to Home Assistant sensors."""

    def __init__(self, ha: HomeAssistantClient, sensor_prefix: str) -> None:
        self.ha = ha
        self.prefix = sensor_prefix  # e.g. "sensor.pv_ai_forecast"

    async def publish(self, forecast: FullForecast) -> None:
        """Push all forecast sensors to Home Assistant."""
        sensors: list[tuple[str, str, dict[str, Any]]] = []

        # --- Combined totals ---
        sensors.append((
            f"{self.prefix}_today_kwh",
            str(round(forecast.today_total_kwh, 2)),
            {
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "friendly_name": "PV AI Forecast Today",
                "icon": "mdi:solar-power-variant",
                "last_updated": forecast.timestamp.isoformat(),
            },
        ))
        sensors.append((
            f"{self.prefix}_today_remaining_kwh",
            str(round(forecast.today_remaining_kwh, 2)),
            {
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "friendly_name": "PV AI Forecast Today Remaining",
                "icon": "mdi:solar-power-variant",
                "last_updated": forecast.timestamp.isoformat(),
            },
        ))
        sensors.append((
            f"{self.prefix}_tomorrow_kwh",
            str(round(forecast.tomorrow_total_kwh, 2)),
            {
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "friendly_name": "PV AI Forecast Tomorrow",
                "icon": "mdi:solar-power-variant",
                "last_updated": forecast.timestamp.isoformat(),
            },
        ))
        sensors.append((
            f"{self.prefix}_day_after_tomorrow_kwh",
            str(round(forecast.day_after_total_kwh, 2)),
            {
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "friendly_name": "PV AI Forecast Day After Tomorrow",
                "icon": "mdi:solar-power-variant",
                "last_updated": forecast.timestamp.isoformat(),
            },
        ))

        # --- Per-array sensors ---
        for arr_name, arr in [("east", forecast.east), ("west", forecast.west)]:
            if arr is None:
                continue

            for day_key, day_label in [("today", "Today"), ("tomorrow", "Tomorrow")]:
                day: DayForecast | None = getattr(arr, day_key, None)
                value = str(round(day.total_kwh, 2)) if day else "0"
                sensors.append((
                    f"{self.prefix}_{arr_name}_{day_key}_kwh",
                    value,
                    {
                        **_array_attrs(arr, day_key),
                        "friendly_name": f"PV AI Forecast {arr_name.title()} {day_label}",
                        "icon": "mdi:solar-power-variant",
                        "last_updated": forecast.timestamp.isoformat(),
                    },
                ))

        # Push all sensors to HA
        for entity_id, state, attributes in sensors:
            try:
                await self._set_state(entity_id, state, attributes)
            except Exception:
                logger.exception("sensor_publish_failed", entity_id=entity_id)

        logger.info("sensors_published", count=len(sensors))

    async def _set_state(
        self, entity_id: str, state: str, attributes: dict[str, Any]
    ) -> None:
        """Create or update a sensor in Home Assistant."""
        client = await self.ha._get_client()
        resp = await client.post(
            f"/states/{entity_id}",
            json={"state": state, "attributes": attributes},
        )
        resp.raise_for_status()
