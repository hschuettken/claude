"""HEMS orchestrator tool handlers (#1084 #1085 #1086).

Tool handlers that respond to orchestrator calls for:
- get_battery_roi_status: Battery ROI tracking
- get_oven_recommendation: Wood oven lighting recommendation
- get_energy_economics: Current energy economics snapshot
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("hems.orchestrator_tools")

# Configuration from environment variables
BATTERY_CAPACITY_KWH = float(os.getenv("BATTERY_CAPACITY_KWH", "7.0"))
ELECTRICITY_PRICE_EUR_KWH = float(os.getenv("ELECTRICITY_PRICE", "0.32"))
GAS_PRICE_EUR_KWH = float(os.getenv("GAS_PRICE", "0.12"))
OUTSIDE_TEMP = float(os.getenv("OUTSIDE_TEMP", "5.0"))


async def get_battery_roi_status() -> dict[str, Any]:
    """Return battery ROI tracking data.

    Calculates: energy_stored_kwh, discharge_kwh, cycles, estimated_savings_eur.
    Tries to read from InfluxDB pv_budget_allocation measurement.
    Falls back to env-var config if InfluxDB unavailable.

    Returns:
        Dict with:
            battery_capacity_kwh: Total battery capacity (kWh)
            estimated_daily_cycles: Estimated daily charge/discharge cycles
            daily_savings_eur: Estimated daily savings from battery dispatch (EUR)
            payback_years: Estimated payback period (years)
            status: "tracking" or "unavailable"
    """
    try:
        # Attempt to query InfluxDB for battery cycle data
        from influxdb_client import InfluxDBClient

        influx_url = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
        influx_token = os.getenv("INFLUXDB_TOKEN", "")
        influx_org = os.getenv("INFLUXDB_ORG", "nb9")

        client = InfluxDBClient(
            url=influx_url,
            token=influx_token,
            org=influx_org,
        )
        query_api = client.query_api()

        # Query total energy stored and discharged today
        # Assuming measurements: battery_state with power_kw field
        query = """
from(bucket: "hems")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "battery_state")
  |> filter(fn: (r) => r._field == "power_kw")
  |> sum()
"""
        result = query_api.query(query)

        total_energy_kwh = 0.0
        for table in result:
            for record in table.records:
                if record.value is not None:
                    # sum() returns total kW·minutes; divide by 60 for kWh
                    total_energy_kwh += float(record.value) / 60.0

        client.close()

        # Estimate cycles: full cycle ≈ 2× capacity moved per day
        estimated_daily_cycles = max(
            0.8, abs(total_energy_kwh) / BATTERY_CAPACITY_KWH / 2
        )

        # Savings: assume arbitrage of 0.15 EUR/kWh (grid price premium)
        daily_savings_eur = (total_energy_kwh / 2) * 0.15

        # Payback: 7kWh × 200 EUR/kWh cost / annual_savings
        battery_cost_eur = BATTERY_CAPACITY_KWH * 200
        annual_savings_eur = daily_savings_eur * 365
        payback_years = (
            battery_cost_eur / annual_savings_eur if annual_savings_eur > 0 else 10.0
        )

        logger.info(
            "Battery ROI: %d cycles/day, %.2f EUR/day savings, %.1f year payback",
            int(estimated_daily_cycles),
            daily_savings_eur,
            payback_years,
        )

        return {
            "battery_capacity_kwh": float(BATTERY_CAPACITY_KWH),
            "estimated_daily_cycles": round(estimated_daily_cycles, 2),
            "daily_savings_eur": round(daily_savings_eur, 2),
            "payback_years": round(payback_years, 1),
            "status": "tracking",
        }

    except Exception as e:
        logger.warning("Failed to query battery ROI from InfluxDB: %s", e)
        # Fallback to conservative defaults
        return {
            "battery_capacity_kwh": float(BATTERY_CAPACITY_KWH),
            "estimated_daily_cycles": 0.8,
            "daily_savings_eur": 0.0,
            "payback_years": 10.0,
            "status": "unavailable",
        }


async def get_oven_recommendation() -> dict[str, Any]:
    """Return wood oven lighting recommendation.

    Uses WoodOvenAdvisor to calculate optimal start time based on:
    - Current inside temperature (from HA sensor or config)
    - Outside temperature (from env or HA)
    - Target evening temperature and time

    Returns:
        Dict with:
            light_oven: bool — whether to light the oven now
            start_time: ISO8601 string or None
            reason: str explaining the recommendation
    """
    try:
        from wood_oven_advisor import WoodOvenAdvisor

        # Get current temperatures
        # Current room temp: try HA first, fallback to env
        current_temp = float(os.getenv("CURRENT_ROOM_TEMP", "18.0"))
        outside_temp = float(os.getenv("OUTSIDE_TEMP", "5.0"))

        advisor = WoodOvenAdvisor()
        recommendation = advisor.get_daily_recommendation(
            current_temp=current_temp,
            outside_temp=outside_temp,
            target_evening_temp=21.0,
            evening_hour=18,
        )

        # Decide whether to light now based on urgency
        light_oven = recommendation["urgency"] in ("urgent", "soon")

        logger.info(
            "Oven recommendation: light=%s, reason=%s",
            light_oven,
            recommendation["advice"],
        )

        return {
            "light_oven": light_oven,
            "start_time": recommendation["start_time"],
            "reason": recommendation["advice"],
        }

    except Exception as e:
        logger.warning("Failed to compute oven recommendation: %s", e)
        return {
            "light_oven": False,
            "start_time": None,
            "reason": f"Advisor unavailable: {str(e)}",
        }


async def get_energy_economics() -> dict[str, Any]:
    """Return current energy economics snapshot.

    Combines data from:
    - OilSavingsTracker: heating cost savings vs oil baseline
    - EconomicTracker: daily PV fraction and cost
    - Config: current electricity and gas prices

    Returns:
        Dict with:
            electricity_price_eur_kwh: Current grid electricity price
            gas_price_eur_kwh: Current gas price equivalent
            pv_fraction_today: Fraction of today's energy from PV (0.0–1.0)
            savings_today_eur: Estimated savings today vs oil baseline (EUR)
            status: "available" or "partial"
    """
    try:
        from economic_tracker import EconomicTracker
        from datetime import date

        tracker = EconomicTracker()
        today = date.today()

        # Compute today's summary so far
        summary = await tracker.compute_daily_summary(today)

        if "error" in summary:
            # Partial data — return what we can
            logger.warning("Economic tracker error: %s", summary.get("error"))
            pv_fraction = 0.0
            savings_today_eur = 0.0
            status = "partial"
        else:
            # Calculate PV fraction of total energy
            total_kwh = summary.get("total_heating_kwh", 0.0)
            pv_kwh = summary.get("pv_kwh", 0.0)
            pv_fraction = (pv_kwh / total_kwh) if total_kwh > 0 else 0.0
            savings_today_eur = summary.get("savings_vs_gas_eur", 0.0)
            status = "available"

        logger.info(
            "Energy economics: %.1f%% PV, %.2f EUR savings",
            pv_fraction * 100,
            savings_today_eur,
        )

        return {
            "electricity_price_eur_kwh": float(ELECTRICITY_PRICE_EUR_KWH),
            "gas_price_eur_kwh": float(GAS_PRICE_EUR_KWH),
            "pv_fraction_today": round(pv_fraction, 2),
            "savings_today_eur": round(savings_today_eur, 2),
            "status": status,
        }

    except Exception as e:
        logger.warning("Failed to compute energy economics: %s", e)
        return {
            "electricity_price_eur_kwh": float(ELECTRICITY_PRICE_EUR_KWH),
            "gas_price_eur_kwh": float(GAS_PRICE_EUR_KWH),
            "pv_fraction_today": 0.0,
            "savings_today_eur": 0.0,
            "status": "unavailable",
        }
