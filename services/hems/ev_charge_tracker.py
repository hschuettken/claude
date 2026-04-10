"""EV Charge Tracker — source attribution (#1097).

Tracks EV charging sessions and attributes energy to PV vs grid sources.
Logs allocation decisions to InfluxDB and Postgres for audit/analytics.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)


class EVChargeTracker:
    """Tracks EV charging sessions with PV/grid source attribution."""

    async def log_charge_session(
        self,
        kwh_charged: float,
        pv_available_w: float,
        grid_import_w: float,
        duration_minutes: int,
    ) -> dict:
        """Log a charging session with source attribution.

        Args:
            kwh_charged: Total energy charged in this session (kWh).
            pv_available_w: Average PV power available during session (W).
            grid_import_w: Average grid import power during session (W).
            duration_minutes: Session duration in minutes.

        Returns:
            Dictionary with attribution results:
            {
                "pv_kwh": float,
                "grid_kwh": float,
                "pv_fraction": float,
            }
        """
        # Determine PV/grid attribution
        denominator = pv_available_w + max(grid_import_w, 0.01)
        pv_fraction = min(1.0, pv_available_w / denominator)
        pv_kwh = kwh_charged * pv_fraction
        grid_kwh = kwh_charged * (1.0 - pv_fraction)

        logger.info(
            "EV charge session: %.2f kWh (PV: %.2f kWh, Grid: %.2f kWh, "
            "PV fraction: %.1f%%)",
            kwh_charged,
            pv_kwh,
            grid_kwh,
            pv_fraction * 100.0,
        )

        # Write to InfluxDB (best-effort)
        try:
            from influxdb_setup import write_hems_point

            await write_hems_point(
                measurement="ev_charging",
                fields={
                    "kwh_total": float(kwh_charged),
                    "pv_kwh": float(pv_kwh),
                    "grid_kwh": float(grid_kwh),
                    "pv_fraction": float(pv_fraction),
                },
                tags={"source": "ev_charger"},
            )
        except Exception as e:
            logger.warning("InfluxDB ev_charging write failed: %s", e)

        # Write to Postgres hems.energy_allocation (best-effort)
        try:
            import asyncpg

            pg_url = DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
                "postgresql+psycopg2://", "postgresql://"
            )
            source = "pv" if pv_fraction > 0.5 else "grid"
            # Calculate average watts during the session
            allocated_watts = (
                (kwh_charged / duration_minutes * 60.0 * 1000.0)
                if duration_minutes > 0
                else 0.0
            )

            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    """
                    INSERT INTO hems.energy_allocation
                        (pv_total_w, house_w, dhw_w, ev_w, supplemental_w,
                         grid_export_w, self_consumption_pct)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    0.0,  # pv_total_w
                    0.0,  # house_w
                    0.0,  # dhw_w
                    float(allocated_watts),  # ev_w
                    0.0,  # supplemental_w
                    0.0,  # grid_export_w
                    float(
                        pv_fraction * 100.0
                    ),  # self_consumption_pct (reused as pv_fraction %)
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Postgres ev_charging write failed: %s", e)

        return {
            "pv_kwh": pv_kwh,
            "grid_kwh": grid_kwh,
            "pv_fraction": pv_fraction,
        }

    async def get_attribution_summary(self, days: int = 30) -> dict:
        """Get EV charging attribution summary for last N days.

        Args:
            days: Number of days to look back (default 30).

        Returns:
            Dictionary with aggregated attribution:
            {
                "total_kwh": float,
                "pv_kwh": float,
                "grid_kwh": float,
                "pv_fraction": float,
            }
        """
        try:
            from influxdb_setup import query_hems_data

            # Query EV charging data from InfluxDB for last N days
            results = await query_hems_data(
                measurement="ev_charging",
                days=days,
                tags={"source": "ev_charger"},
            )

            total_pv_kwh = 0.0
            total_grid_kwh = 0.0

            for record in results:
                pv_kwh = record.get("pv_kwh", 0.0)
                grid_kwh = record.get("grid_kwh", 0.0)
                total_pv_kwh += pv_kwh
                total_grid_kwh += grid_kwh

            total_kwh = total_pv_kwh + total_grid_kwh
            pv_fraction = (total_pv_kwh / total_kwh) if total_kwh > 0 else 0.0

            logger.info(
                "EV attribution summary (last %d days): %.2f kWh total "
                "(PV: %.2f kWh, Grid: %.2f kWh, PV fraction: %.1f%%)",
                days,
                total_kwh,
                total_pv_kwh,
                total_grid_kwh,
                pv_fraction * 100.0,
            )

            return {
                "total_kwh": total_kwh,
                "pv_kwh": total_pv_kwh,
                "grid_kwh": total_grid_kwh,
                "pv_fraction": pv_fraction,
            }
        except Exception as e:
            logger.warning("InfluxDB ev_charging summary query failed: %s", e)
            return {
                "total_kwh": 0.0,
                "pv_kwh": 0.0,
                "grid_kwh": 0.0,
                "pv_fraction": 0.0,
            }
