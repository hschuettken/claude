"""InfluxDB v2 client wrapper.

Provides a simple interface for querying sensor data from InfluxDB.

Usage:
    from shared.influx_client import InfluxClient
    from shared.config import Settings

    settings = Settings()
    influx = InfluxClient(
        url=settings.influxdb_url,
        token=settings.influxdb_token,
        org=settings.influxdb_org,
    )

    # Query with Flux
    records = influx.query_records(
        bucket="hass",
        entity_id="sensor.temperature_living_room",
        range_start="-24h",
    )
    for record in records:
        print(record["_time"], record["_value"])

    influx.close()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.flux_table import TableList
from influxdb_client.client.write_api import SYNCHRONOUS

from shared.log import get_logger

logger = get_logger("influx-client")


class InfluxClient:
    """Wrapper around InfluxDB v2 client with convenience methods."""

    def __init__(self, url: str, token: str, org: str) -> None:
        self.org = org
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._query_api = self._client.query_api()
        try:
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        except Exception as exc:
            logger.warning("influx_write_api_init_failed", error=str(exc))
            self._write_api = None

    def close(self) -> None:
        if self._write_api is not None:
            try:
                self._write_api.close()
            except Exception as exc:
                logger.warning("influx_write_api_close_failed", error=str(exc))
        self._client.close()

    def get_write_api_available(self) -> bool:
        """Return True if the write API was successfully initialized."""
        return self._write_api is not None

    def write_point(
        self,
        bucket: str,
        measurement: str,
        fields: dict[str, Any],
        tags: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Write a single data point to InfluxDB."""
        if self._write_api is None:
            logger.warning("influx_write_skipped_no_api", measurement=measurement)
            return
        try:
            point = Point(measurement)
            for key, value in (tags or {}).items():
                point = point.tag(key, value)
            for key, value in fields.items():
                point = point.field(key, value)
            if timestamp is not None:
                point = point.time(timestamp)
            self._write_api.write(bucket=bucket, org=self.org, record=point)
            logger.debug("influx_point_written", bucket=bucket, measurement=measurement)
        except Exception as exc:
            logger.warning(
                "influx_write_failed",
                bucket=bucket,
                measurement=measurement,
                error=str(exc),
            )

    def write_points(
        self,
        bucket: str,
        points: list[dict],
    ) -> None:
        """Write multiple points.

        Each dict: {measurement, fields, tags?, timestamp?}
        """
        for p in points:
            self.write_point(
                bucket=bucket,
                measurement=p["measurement"],
                fields=p["fields"],
                tags=p.get("tags"),
                timestamp=p.get("timestamp"),
            )

    def query_raw(self, flux_query: str) -> TableList:
        """Execute a raw Flux query and return tables."""
        logger.debug("influx_query", query=flux_query[:200])
        return self._query_api.query(flux_query, org=self.org)

    def query_records(
        self,
        bucket: str,
        measurement: str | None = None,
        entity_id: str | None = None,
        field: str = "value",
        range_start: str = "-1h",
        range_stop: str = "now()",
    ) -> list[dict[str, Any]]:
        """Query records with common filters.

        Args:
            bucket: InfluxDB bucket name.
            measurement: Filter by _measurement (e.g., "kWh", "W", "°C").
            entity_id: Filter by entity_id tag. Accepts full HA entity IDs
                like "sensor.temperature" — the "sensor." domain prefix is
                stripped automatically since HA stores it in a separate
                "domain" tag in InfluxDB.
            field: Filter by _field (default: "value").
            range_start: Start of time range (Flux duration or timestamp).
            range_stop: End of time range.

        Returns:
            List of record dicts with _time, _value, and tag fields.
        """
        filters = []
        if measurement:
            filters.append(
                f'|> filter(fn: (r) => r["_measurement"] == "{measurement}")'
            )
        if entity_id:
            # HA stores entity_id without domain prefix in InfluxDB
            # e.g. "sensor.inverter_pv_east_energy" → entity_id="inverter_pv_east_energy", domain="sensor"
            influx_entity_id = (
                entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
            )
            filters.append(
                f'|> filter(fn: (r) => r["entity_id"] == "{influx_entity_id}")'
            )
        if field:
            filters.append(f'|> filter(fn: (r) => r["_field"] == "{field}")')

        flux = f"""
from(bucket: "{bucket}")
  |> range(start: {range_start}, stop: {range_stop})
  {chr(10).join(f"  {f}" for f in filters)}
"""
        tables = self.query_raw(flux.strip())
        return [record.values for table in tables for record in table.records]

    def query_mean(
        self,
        bucket: str,
        entity_id: str,
        range_start: str = "-24h",
        window: str = "1h",
    ) -> list[dict[str, Any]]:
        """Query windowed mean values for an entity — useful for trends."""
        influx_entity_id = (
            entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
        )
        flux = f"""
from(bucket: "{bucket}")
  |> range(start: {range_start})
  |> filter(fn: (r) => r["entity_id"] == "{influx_entity_id}")
  |> filter(fn: (r) => r["_field"] == "value")
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> yield(name: "mean")
"""
        tables = self.query_raw(flux.strip())
        return [record.values for table in tables for record in table.records]
