"""Oil savings baseline comparison tracker (#1078).

Computes oil heating cost baseline and actual savings from heat pump operation.
Compares actual heating energy cost vs equivalent heating oil cost.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)

# Configuration from environment variables
OIL_PRICE_EUR_PER_LITER = float(os.getenv("OIL_PRICE_EUR_LITER", "1.20"))
OIL_KWH_PER_LITER = float(
    os.getenv("OIL_KWH_PER_LITER", "10.0")
)  # ~10 kWh/liter heating oil
OIL_BOILER_EFFICIENCY = float(os.getenv("OIL_BOILER_EFFICIENCY", "0.85"))

ELECTRICITY_PRICE_EUR_KWH = float(os.getenv("ELECTRICITY_PRICE", "0.32"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUXDB_BUCKET = "hems"


class OilSavingsTracker:
    """Track heating cost savings vs oil baseline."""

    def __init__(
        self,
        db_url: str = DATABASE_URL,
        influx_url: str = INFLUXDB_URL,
        influx_token: str = INFLUXDB_TOKEN,
        influx_org: str = INFLUXDB_ORG,
    ):
        self.db_url = db_url
        self.influx_url = influx_url
        self.influx_token = influx_token
        self.influx_org = influx_org

    def compute_baseline_cost(self, heating_kwh: float) -> float:
        """Compute cost of equivalent heating oil to provide heating_kwh.

        Args:
            heating_kwh: Total heating energy needed (kWh)

        Returns:
            Cost in EUR to provide that energy via oil boiler
        """
        liters_needed = heating_kwh / (OIL_KWH_PER_LITER * OIL_BOILER_EFFICIENCY)
        return liters_needed * OIL_PRICE_EUR_PER_LITER

    async def compute_savings_report(self, days: int = 30) -> dict:
        """Compute oil savings report for the past N days.

        Args:
            days: Number of days to analyze (default 30)

        Returns:
            {
                "period_days": int,
                "actual_kwh": float,
                "actual_cost_eur": float,
                "oil_baseline_cost_eur": float,
                "savings_eur": float,
                "savings_pct": float,
                "co2_avoided_kg": float,
            }

        Queries InfluxDB for boiler energy, computes actual electricity cost.
        On error, returns dummy data with fallback values.
        """
        try:
            # Query boiler energy from InfluxDB for the past N days
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            actual_kwh = await self._query_boiler_energy(start_date, end_date)

            # Compute actual cost (electricity price for the energy consumed)
            actual_cost_eur = actual_kwh * ELECTRICITY_PRICE_EUR_KWH

            # Compute oil baseline (what it would cost with oil boiler)
            oil_baseline_cost_eur = self.compute_baseline_cost(actual_kwh)

            # Savings and CO2 avoided
            savings_eur = oil_baseline_cost_eur - actual_cost_eur
            savings_pct = (
                (savings_eur / oil_baseline_cost_eur * 100)
                if oil_baseline_cost_eur > 0
                else 0.0
            )

            # CO2 avoided: assume grid electricity = 0.4 kg CO2 per kWh
            # Oil avoidance saves: ~3.15 kg CO2 per liter
            # But we measure in kWh displacement from grid perspective
            pv_kwh_used = await self._query_pv_contribution(start_date, end_date)
            co2_avoided_kg = pv_kwh_used * 0.4  # Grid CO2 intensity avoided

            return {
                "period_days": days,
                "actual_kwh": round(actual_kwh, 2),
                "actual_cost_eur": round(actual_cost_eur, 2),
                "oil_baseline_cost_eur": round(oil_baseline_cost_eur, 2),
                "savings_eur": round(savings_eur, 2),
                "savings_pct": round(savings_pct, 1),
                "co2_avoided_kg": round(co2_avoided_kg, 2),
            }

        except Exception as e:
            logger.error("Failed to compute oil savings report: %s", e)
            # Fallback to dummy data
            return {
                "period_days": days,
                "actual_kwh": 0.0,
                "actual_cost_eur": 0.0,
                "oil_baseline_cost_eur": 0.0,
                "savings_eur": 0.0,
                "savings_pct": 0.0,
                "co2_avoided_kg": 0.0,
                "error": str(e),
            }

    async def _query_boiler_energy(
        self,
        start: datetime,
        end: datetime,
    ) -> float:
        """Query InfluxDB for boiler energy (kWh) between start and end times.

        Returns 0.0 on error (best-effort).
        """
        try:
            from influxdb_client import InfluxDBClient

            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
            )
            query_api = client.query_api()

            query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> filter(fn: (r) => r._measurement == "boiler_state")
  |> filter(fn: (r) => r._field == "power_kw")
  |> sum()
'''
            result = query_api.query(query)

            total_kwh = 0.0
            for table in result:
                for record in table.records:
                    if record.value is not None:
                        # sum() returns total kW·minutes; divide by 60 for kWh
                        total_kwh += float(record.value) / 60.0

            client.close()
            return total_kwh

        except Exception as e:
            logger.warning("InfluxDB boiler_energy query failed: %s", e)
            return 0.0

    async def _query_pv_contribution(
        self,
        start: datetime,
        end: datetime,
    ) -> float:
        """Query InfluxDB for PV energy allocated to heating (kWh).

        Returns 0.0 on error (best-effort).
        """
        try:
            from influxdb_client import InfluxDBClient

            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
            )
            query_api = client.query_api()

            query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> filter(fn: (r) => r._measurement == "pv_budget_allocation")
  |> filter(fn: (r) => r._field == "pv_kw")
  |> sum()
'''
            result = query_api.query(query)

            total_kwh = 0.0
            for table in result:
                for record in table.records:
                    if record.value is not None:
                        # sum() returns total kW·minutes; divide by 60 for kWh
                        total_kwh += float(record.value) / 60.0

            client.close()
            return total_kwh

        except Exception as e:
            logger.warning("InfluxDB pv_contribution query failed: %s", e)
            return 0.0

    async def save_report_to_influxdb(self, report: dict) -> None:
        """Save oil savings report to InfluxDB hems_oil_savings measurement."""
        if "error" in report and len(report) == 2:  # Only error + period_days
            logger.warning("Skipping InfluxDB save due to error in report")
            return

        try:
            from influxdb_client import InfluxDBClient, Point

            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
            )
            write_api = client.write_api()

            point = (
                Point("hems_oil_savings")
                .time(datetime.now(timezone.utc), write_precision="ns")
                .field("actual_kwh", report.get("actual_kwh", 0.0))
                .field("actual_cost_eur", report.get("actual_cost_eur", 0.0))
                .field(
                    "oil_baseline_cost_eur", report.get("oil_baseline_cost_eur", 0.0)
                )
                .field("savings_eur", report.get("savings_eur", 0.0))
                .field("savings_pct", report.get("savings_pct", 0.0))
                .field("co2_avoided_kg", report.get("co2_avoided_kg", 0.0))
                .tag("period_days", str(report.get("period_days", 30)))
            )

            write_api.write(
                bucket=INFLUXDB_BUCKET,
                org=self.influx_org,
                record=point,
            )
            logger.info("Oil savings report saved to InfluxDB")
            client.close()

        except Exception as e:
            logger.warning("InfluxDB save failed for oil savings report: %s", e)
