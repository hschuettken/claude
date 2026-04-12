"""InfluxDB metrics writer for Kairos companion agent."""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import ASYNCHRONOUS

logger = logging.getLogger(__name__)


class KairosMetrics:
    """Writes Kairos token usage and latency metrics to InfluxDB.

    All InfluxDB errors are non-fatal — errors are logged and execution continues.
    """

    def __init__(
        self,
        url: str = "http://192.168.0.66:8086",
        org: str = "nb9",
        bucket: str = "nb9os",
    ) -> None:
        self._url = url
        self._org = org
        self._bucket = bucket
        self._token = os.environ.get("INFLUXDB_TOKEN", "")
        self._client: Optional[InfluxDBClient] = None
        self._write_api = None

    def _ensure_client(self) -> bool:
        """Lazily initialise InfluxDB client. Returns True if ready."""
        if self._client is not None:
            return True
        if not self._token:
            logger.warning("kairos_metrics_no_influx_token")
            return False
        try:
            self._client = InfluxDBClient(
                url=self._url,
                token=self._token,
                org=self._org,
            )
            self._write_api = self._client.write_api(
                write_options=WriteOptions(write_type=ASYNCHRONOUS)
            )
            logger.info("kairos_metrics_influx_connected", url=self._url)
            return True
        except Exception as exc:
            logger.warning("kairos_metrics_influx_init_failed", error=str(exc))
            self._client = None
            self._write_api = None
            return False

    async def record_response(
        self,
        user_id: str,
        token_count: int,
        latency_ms: int,
        tool_calls_count: int = 0,
    ) -> None:
        """Record a response event to InfluxDB measurement kairos_usage."""
        if not self._ensure_client():
            return
        try:
            point = (
                Point("kairos_usage")
                .tag("user_id", user_id)
                .tag("event_type", "response")
                .field("token_count", token_count)
                .field("latency_ms", latency_ms)
                .field("tool_calls_count", tool_calls_count)
                .time(datetime.now(timezone.utc))
            )
            self._write_api.write(bucket=self._bucket, org=self._org, record=point)
        except Exception as exc:
            logger.warning(
                "kairos_metrics_record_response_failed",
                user_id=user_id,
                error=str(exc),
            )

    async def record_cost_snapshot(
        self,
        user_id: str,
        daily_tokens_used: int,
        daily_cap: int,
    ) -> None:
        """Record daily token budget snapshot to InfluxDB measurement kairos_usage."""
        if not self._ensure_client():
            return
        try:
            pct_used = (daily_tokens_used / daily_cap * 100.0) if daily_cap > 0 else 0.0
            point = (
                Point("kairos_usage")
                .tag("user_id", user_id)
                .tag("event_type", "cost_snapshot")
                .field("daily_tokens_used", daily_tokens_used)
                .field("daily_cap", daily_cap)
                .field("pct_used", pct_used)
                .time(datetime.now(timezone.utc))
            )
            self._write_api.write(bucket=self._bucket, org=self._org, record=point)
        except Exception as exc:
            logger.warning(
                "kairos_metrics_record_cost_snapshot_failed",
                user_id=user_id,
                error=str(exc),
            )

    async def close(self) -> None:
        """Flush and close the InfluxDB client."""
        if self._write_api is not None:
            try:
                self._write_api.close()
            except Exception as exc:
                logger.warning("kairos_metrics_write_api_close_failed", error=str(exc))
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.warning("kairos_metrics_influx_close_failed", error=str(exc))
            self._client = None
            self._write_api = None
