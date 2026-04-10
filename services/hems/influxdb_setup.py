"""InfluxDB bucket setup for HEMS (#1035).

Bucket: hems, retention: 365 days
Measurements:
  - hems.mixer_control: PI loop data
  - hems.boiler_state: boiler on/off/mode
  - hems.decisions: HEMS decisions audit trail
  - hems.energy_allocation: PV budget allocations
  - hems.nn_training_log: Neural network training metrics
  - thermal_training: thermal model training data (every 5min)

Run standalone:
    python influxdb_setup.py
Or call ensure_hems_bucket() at startup.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

INFLUX_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUX_BUCKET = "hems"
INFLUX_RETENTION_DAYS = 365


async def ensure_hems_bucket() -> bool:
    """Create HEMS InfluxDB bucket if it doesn't exist.

    Returns True if the bucket exists or was successfully created.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check whether bucket already exists
            r = await client.get(
                f"{INFLUX_URL}/api/v2/buckets",
                headers={"Authorization": f"Token {INFLUX_TOKEN}"},
                params={"name": INFLUX_BUCKET},
            )
            if r.status_code == 200 and r.json().get("buckets"):
                logger.info("InfluxDB bucket '%s' already exists", INFLUX_BUCKET)
                return True

            # Resolve org ID
            orgs_r = await client.get(
                f"{INFLUX_URL}/api/v2/orgs",
                headers={"Authorization": f"Token {INFLUX_TOKEN}"},
            )
            if orgs_r.status_code != 200:
                logger.error("Failed to list InfluxDB orgs: %s", orgs_r.text[:200])
                return False

            orgs = orgs_r.json().get("orgs", [])
            org_id = next((o["id"] for o in orgs if o["name"] == INFLUX_ORG), None)
            if not org_id:
                logger.error("Org '%s' not found in InfluxDB", INFLUX_ORG)
                return False

            # Create the bucket
            create_r = await client.post(
                f"{INFLUX_URL}/api/v2/buckets",
                headers={
                    "Authorization": f"Token {INFLUX_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": INFLUX_BUCKET,
                    "orgID": org_id,
                    "description": "HEMS energy telemetry — mixer control, boiler, PV allocation, NN training",
                    "retentionRules": [
                        {
                            "type": "expire",
                            "everySeconds": INFLUX_RETENTION_DAYS * 86400,
                        }
                    ],
                },
            )
            if create_r.status_code == 201:
                logger.info(
                    "Created InfluxDB bucket '%s' (retention: %d days)",
                    INFLUX_BUCKET,
                    INFLUX_RETENTION_DAYS,
                )
                return True
            else:
                logger.error("Failed to create bucket: %s", create_r.text[:400])
                return False

    except Exception as e:
        logger.error("InfluxDB bucket setup failed: %s", e)
        return False


async def write_hems_point(
    measurement: str,
    fields: dict,
    tags: Optional[dict] = None,
) -> None:
    """Write a single data point to the hems bucket via the line-protocol API.

    Uses httpx directly (no influxdb-client dependency) so this module stays
    lightweight and importable without the full SDK installed.

    Args:
        measurement: InfluxDB measurement name (e.g. "hems.mixer_control").
        fields: Dict of field key → value. Integers are written with the ``i``
                suffix; floats and strings are handled automatically.
        tags: Optional dict of tag key → value. Tag values must be strings.
    """
    try:
        import httpx
        from datetime import datetime, timezone

        # Build tag set string
        tag_str = ""
        if tags:
            tag_str = "," + ",".join(f"{k}={v}" for k, v in sorted(tags.items()))

        # Build field set string
        field_parts: list[str] = []
        for k, v in fields.items():
            if isinstance(v, bool):
                # bool must come before int check (bool is a subclass of int)
                field_parts.append(f"{k}={str(v).lower()}")
            elif isinstance(v, int):
                field_parts.append(f"{k}={v}i")
            elif isinstance(v, float):
                field_parts.append(f"{k}={v}")
            else:
                # Escape double-quotes in string field values
                escaped = str(v).replace('"', '\\"')
                field_parts.append(f'{k}="{escaped}"')

        field_str = ",".join(field_parts)
        ns_ts = int(datetime.now(timezone.utc).timestamp() * 1e9)
        line = f"{measurement}{tag_str} {field_str} {ns_ts}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{INFLUX_URL}/api/v2/write",
                headers={
                    "Authorization": f"Token {INFLUX_TOKEN}",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                params={
                    "org": INFLUX_ORG,
                    "bucket": INFLUX_BUCKET,
                    "precision": "ns",
                },
                content=line,
            )
            if r.status_code not in (200, 204):
                logger.warning(
                    "InfluxDB write failed (%s) for measurement '%s': %s",
                    r.status_code,
                    measurement,
                    r.text[:200],
                )
    except Exception as e:
        logger.warning("InfluxDB write error for measurement '%s': %s", measurement, e)


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def _main() -> None:
        ok = await ensure_hems_bucket()
        sys.exit(0 if ok else 1)

    asyncio.run(_main())
