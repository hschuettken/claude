"""EconomicTracker — daily cost/savings summary for HEMS (#1074).

Computes daily heating costs and PV savings by querying InfluxDB and PostgreSQL.
Runs daily at 23:55 to log previous day's summary.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, date, time, timedelta, timezone

import asyncpg

logger = logging.getLogger("hems.economic_tracker")

# Config from env
ELECTRICITY_PRICE_EUR_KWH = float(os.getenv("ELECTRICITY_PRICE", "0.32"))
GAS_PRICE_EUR_KWH = float(os.getenv("GAS_PRICE", "0.12"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUXDB_BUCKET = "hems"


class EconomicTracker:
    """Daily heating cost and savings tracker."""

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

    async def compute_daily_summary(self, target_date: date) -> dict:
        """Compute daily heating cost and PV savings summary.

        Args:
            target_date: Date to summarize (e.g., yesterday)

        Returns:
            {
                "date": "2026-04-09",
                "total_heating_kwh": 18.5,
                "pv_kwh": 12.3,
                "grid_kwh": 6.2,
                "cost_eur": 1.98,
                "savings_vs_gas_eur": 0.34,
            }

        On any error, returns minimal dict with error key.
        """
        try:
            # Query InfluxDB for boiler energy and PV contribution
            boiler_kwh = await self._query_boiler_energy(target_date)
            pv_kwh = await self._query_pv_contribution(target_date)

            # Compute grid energy (boiler - pv)
            grid_kwh = max(0, boiler_kwh - pv_kwh)

            # Cost: grid kWh at electricity price + boiler baseline
            cost_eur = grid_kwh * ELECTRICITY_PRICE_EUR_KWH

            # Savings vs gas: PV displacement saves at (GAS_PRICE - ELEC_PRICE) per kWh
            # We save gas cost on PV energy, minus the grid cost we'd pay anyway
            savings_vs_gas_eur = pv_kwh * (
                GAS_PRICE_EUR_KWH - ELECTRICITY_PRICE_EUR_KWH
            )

            return {
                "date": target_date.isoformat(),
                "total_heating_kwh": round(boiler_kwh, 2),
                "pv_kwh": round(pv_kwh, 2),
                "grid_kwh": round(grid_kwh, 2),
                "cost_eur": round(cost_eur, 2),
                "savings_vs_gas_eur": round(savings_vs_gas_eur, 2),
            }
        except Exception as e:
            logger.error("Failed to compute daily summary for %s: %s", target_date, e)
            return {
                "date": target_date.isoformat(),
                "error": str(e),
            }

    async def _query_boiler_energy(self, target_date: date) -> float:
        """Query InfluxDB for total boiler energy (kWh) on a date.

        Sums boiler_state measurement power_kw field * 1/60 for per-minute kWh.
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

            # Flux query: sum power over day, convert to kWh
            start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
            end = datetime.combine(
                target_date + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )

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

    async def _query_pv_contribution(self, target_date: date) -> float:
        """Query InfluxDB for PV energy allocated to heating (kWh) on a date.

        Sums pv_budget_allocation measurement pv_kw field.
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

            # Flux query: sum PV allocated to heating
            start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
            end = datetime.combine(
                target_date + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )

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

    async def _save_to_postgres(self, summary: dict) -> None:
        """Save daily summary to PostgreSQL hems.decisions table.

        action='daily_summary', new_value is the full summary JSON.
        """
        if "error" in summary:
            logger.warning(
                "Skipping Postgres save for %s (error in summary)",
                summary.get("date"),
            )
            return

        try:

            pg_url = self.db_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            ).replace("postgresql+psycopg2://", "postgresql://")
            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    """
                    INSERT INTO hems.decisions
                        (mode, flow_temp_setpoint, reason, pv_available_w, outdoor_temp_c)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    "economic",  # mode
                    summary.get(
                        "total_heating_kwh", 0
                    ),  # flow_temp_setpoint (repurposed)
                    f"daily_summary: {summary['date']}",  # reason
                    summary.get("pv_kwh", 0),  # pv_available_w (repurposed)
                    summary.get("cost_eur", 0),  # outdoor_temp_c (repurposed)
                )
                logger.info("Daily summary saved to Postgres: %s", summary["date"])
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Postgres save failed for daily summary: %s", e)

    async def _save_to_influxdb(self, summary: dict) -> None:
        """Save daily summary to InfluxDB hems_economics measurement."""
        if "error" in summary:
            logger.warning(
                "Skipping InfluxDB save for %s (error in summary)",
                summary.get("date"),
            )
            return

        try:
            from influxdb_client import InfluxDBClient, Point

            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
            )
            write_api = client.write_api(write_options=None)  # async/buffered

            # Create point with date timestamp
            target_date = datetime.fromisoformat(summary["date"])
            point_time = datetime.combine(
                target_date.date(),
                time(hour=23, minute=59, second=59),
                tzinfo=timezone.utc,
            )

            point = (
                Point("hems_economics")
                .tag("date", summary["date"])
                .field("total_heating_kwh", float(summary["total_heating_kwh"]))
                .field("pv_kwh", float(summary["pv_kwh"]))
                .field("grid_kwh", float(summary["grid_kwh"]))
                .field("cost_eur", float(summary["cost_eur"]))
                .field("savings_vs_gas_eur", float(summary["savings_vs_gas_eur"]))
                .time(point_time)
            )

            write_api.write(bucket=INFLUXDB_BUCKET, record=point)
            logger.info("Daily summary saved to InfluxDB: %s", summary["date"])
            client.close()

        except Exception as e:
            logger.warning("InfluxDB save failed for daily summary: %s", e)

    async def run_daily_summary(self) -> None:
        """Run daily summary at 23:55 (cron-like).

        Sleeps until 23:55, then computes and saves previous day's summary.
        Loops forever.
        """
        while True:
            now = datetime.now()

            # Next 23:55 target
            target = now.replace(hour=23, minute=55, second=0, microsecond=0)
            if now >= target:
                # If we've already passed 23:55 today, target tomorrow
                target += timedelta(days=1)

            sleep_seconds = (target - now).total_seconds()
            logger.info(
                "Daily summary job: sleeping %.1f seconds until %s",
                sleep_seconds,
                target.isoformat(),
            )

            await asyncio.sleep(sleep_seconds)

            # Compute and save summary for yesterday
            yesterday = date.today() - timedelta(days=1)
            logger.info("Computing daily summary for %s", yesterday)

            summary = await self.compute_daily_summary(yesterday)
            logger.info("Daily summary: %s", summary)

            # Save to both databases
            await self._save_to_postgres(summary)
            await self._save_to_influxdb(summary)
