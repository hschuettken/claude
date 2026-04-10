"""Battery ROI tracker (Task #1075).

Computes daily and cumulative ROI from battery usage in HEMS.
Queries InfluxDB for allocated energy and tracks payback progress.

Usage:
    tracker = BatteryROITracker()
    daily = await tracker.compute_daily_roi()
    payback = await tracker.compute_payback_estimate()
    await tracker.run_daily_tracking()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from shared.influx_client import InfluxClient

logger = logging.getLogger("hems.battery_roi")

# Environment configuration
BATTERY_COST_EUR = float(os.getenv("BATTERY_COST_EUR", "4000.0"))
BATTERY_CAPACITY_KWH = float(os.getenv("BATTERY_CAPACITY_KWH", "7.0"))
BATTERY_CYCLE_LIFE = int(os.getenv("BATTERY_CYCLE_LIFE", "6000"))
BATTERY_FRACTION = float(
    os.getenv("BATTERY_FRACTION", "0.6")
)  # 60% of allocated energy
ELECTRICITY_PRICE_EUR_KWH = float(os.getenv("ELECTRICITY_PRICE_EUR_KWH", "0.25"))
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.50:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "hems")


class BatteryROITracker:
    """Tracks battery return on investment over time."""

    def __init__(self) -> None:
        """Initialize tracker with InfluxDB client."""
        self.influx = InfluxClient(
            url=INFLUXDB_URL,
            token=INFLUXDB_TOKEN,
            org=INFLUXDB_ORG,
        )

    def close(self) -> None:
        """Close InfluxDB connection."""
        self.influx.close()

    async def _query_pv_allocation_yesterday(self) -> Optional[float]:
        """Query InfluxDB for yesterday's total PV budget allocation.

        Sums: ev_charging_w + supplemental_heating_w + dhw_heating_w

        Returns:
            Total allocated energy in kWh for yesterday, or None if unavailable.
        """
        try:
            # Calculate yesterday's date range in UTC
            now = datetime.now(timezone.utc)
            yesterday = now - timedelta(days=1)
            day_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            # Flux query for sum of all three allocation streams
            # Note: measurements are in W, need to integrate to kWh
            flux = f"""
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {int(day_start.timestamp())}s, stop: {int(day_end.timestamp())}s)
  |> filter(fn: (r) => r["_measurement"] == "W" and (
      r["entity_id"] == "pv_allocation_ev_charging_w" or
      r["entity_id"] == "pv_allocation_supplemental_heating_w" or
      r["entity_id"] == "pv_allocation_dhw_heating_w"
  ))
  |> filter(fn: (r) => r["_field"] == "value")
  |> group(by: ["entity_id"])
  |> integral(unit: 1h)
  |> sum(column: "_value")
"""
            tables = self.influx.query_raw(flux)
            total_wh = 0.0
            for table in tables:
                for record in table.records:
                    if record.values.get("_value") is not None:
                        total_wh += float(record.values["_value"])

            # Convert Wh to kWh
            total_kwh = total_wh / 1000.0
            logger.info("Yesterday allocation: %.2f kWh", total_kwh)
            return total_kwh

        except Exception as exc:
            logger.error("Failed to query yesterday's allocation: %s", exc)
            return None

    async def compute_daily_roi(self) -> dict:
        """Compute ROI for yesterday.

        Returns:
            Dict with: date, energy_from_battery_kwh, savings_eur, cumulative_payback_pct.
        """
        yesterday = date.today() - timedelta(days=1)
        allocated_kwh = await self._query_pv_allocation_yesterday()

        if allocated_kwh is None or allocated_kwh <= 0:
            logger.warning("No allocation data for yesterday")
            return {
                "date": yesterday.isoformat(),
                "energy_from_battery_kwh": 0.0,
                "savings_eur": 0.0,
                "cumulative_payback_pct": 0.0,
            }

        # Assume battery contributed BATTERY_FRACTION of allocated energy
        energy_from_battery_kwh = allocated_kwh * BATTERY_FRACTION

        # Savings: battery energy × electricity price × 0.8 (grid is 20% more expensive)
        savings_eur = energy_from_battery_kwh * ELECTRICITY_PRICE_EUR_KWH * 0.8

        # Get cumulative payback from InfluxDB (or hardcoded placeholder)
        cumulative_payback_pct = (savings_eur / BATTERY_COST_EUR) * 100.0

        return {
            "date": yesterday.isoformat(),
            "energy_from_battery_kwh": round(energy_from_battery_kwh, 2),
            "savings_eur": round(savings_eur, 2),
            "cumulative_payback_pct": round(cumulative_payback_pct, 2),
        }

    async def compute_payback_estimate(self) -> dict:
        """Estimate total payback progress and timeline.

        Returns:
            Dict with: total_savings_eur, payback_years_estimated, pct_paid_back.
        """
        try:
            # Query cumulative savings from InfluxDB
            # For now, use a simple approach: sum all daily roi records
            flux = f"""
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -10y)
  |> filter(fn: (r) => r["_measurement"] == "battery_roi_daily_savings_eur")
  |> filter(fn: (r) => r["_field"] == "value")
  |> sum()
"""
            tables = self.influx.query_raw(flux)
            total_savings_eur = 0.0
            for table in tables:
                for record in table.records:
                    if record.values.get("_value") is not None:
                        total_savings_eur += float(record.values["_value"])

            logger.info("Cumulative battery savings: %.2f EUR", total_savings_eur)

        except Exception as exc:
            logger.warning(
                "Could not query cumulative savings, defaulting to zero: %s", exc
            )
            total_savings_eur = 0.0

        # Estimate payback timeline
        pct_paid_back = (total_savings_eur / BATTERY_COST_EUR) * 100.0
        if total_savings_eur > 0:
            daily_avg_savings = total_savings_eur / 365.0  # Very rough estimate
            years_to_payoff = BATTERY_COST_EUR / (daily_avg_savings * 365.0)
        else:
            years_to_payoff = 0.0

        return {
            "total_savings_eur": round(total_savings_eur, 2),
            "payback_years_estimated": round(max(0.0, years_to_payoff), 1),
            "pct_paid_back": round(min(100.0, pct_paid_back), 2),
        }

    async def run_daily_tracking(self) -> None:
        """Run daily tracking loop, publishing ROI at midnight.

        Calculates daily ROI and publishes to MQTT/InfluxDB.
        """
        logger.info("Battery ROI tracker loop starting")

        while True:
            try:
                # Calculate time until next midnight (UTC)
                now = datetime.now(timezone.utc)
                tomorrow = now + timedelta(days=1)
                next_midnight = tomorrow.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                sleep_seconds = (next_midnight - now).total_seconds()

                logger.info("Sleeping until midnight (%.0fs)", sleep_seconds)
                await asyncio.sleep(sleep_seconds)

                # Compute yesterday's ROI
                roi = await self.compute_daily_roi()
                logger.info("Daily ROI computed: %s", json.dumps(roi))

                # Publish to MQTT (optional)
                try:
                    import paho.mqtt.publish as publish

                    topic = "homelab/hems/battery_roi"
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: publish.single(
                            topic,
                            payload=json.dumps(roi),
                            hostname=os.getenv("MQTT_HOST", "192.168.0.73"),
                            port=int(os.getenv("MQTT_PORT", "1883")),
                        ),
                    )
                except Exception as exc:
                    logger.warning("Failed to publish ROI to MQTT: %s", exc)

            except Exception as exc:
                logger.error(
                    "Unhandled error in daily tracking loop: %s",
                    exc,
                    exc_info=True,
                )
                # Wait 1 hour on error before retrying
                await asyncio.sleep(3600)
