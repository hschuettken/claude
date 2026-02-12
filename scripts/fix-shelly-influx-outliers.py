#!/usr/bin/env python3
"""Fix Shelly 3EM energy outliers in InfluxDB.

Analyzes the shelly3em_main_channel_total_energy sensor data around a given date,
detects outlier spikes, and removes them from InfluxDB.

Setup (one-time):
    python3 -m venv scripts/.venv
    source scripts/.venv/bin/activate
    pip install influxdb-client python-dotenv

Usage:
    source scripts/.venv/bin/activate

    # Dry run (default) — show outliers without deleting
    python scripts/fix-shelly-influx-outliers.py

    # Actually delete the outlier points
    python scripts/fix-shelly-influx-outliers.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "homelab")
BUCKET = os.environ.get("INFLUXDB_BUCKET", "hass")

# Sensor to fix (without domain prefix, as stored in InfluxDB)
ENTITY_ID = "shelly3em_main_channel_total_energy"

# Also check + fix per-phase sensors
PHASE_ENTITIES = [
    "shelly3em_main_channel_a_energy",
    "shelly3em_main_channel_b_energy",
    "shelly3em_main_channel_c_energy",
]

# Date range to analyze (wide enough to see context)
RANGE_START = "2025-10-05T00:00:00Z"
RANGE_STOP = "2025-10-08T00:00:00Z"

# Threshold: a jump between consecutive points larger than this (kWh) is an outlier
OUTLIER_THRESHOLD_KWH = 500.0


def query_sensor_data(
    client: InfluxDBClient, entity_id: str, range_start: str, range_stop: str,
) -> list[dict]:
    """Query all data points for a sensor in the analysis window."""
    query_api = client.query_api()
    flux = f"""
from(bucket: "{BUCKET}")
  |> range(start: {range_start}, stop: {range_stop})
  |> filter(fn: (r) => r["entity_id"] == "{entity_id}")
  |> filter(fn: (r) => r["_field"] == "value")
  |> sort(columns: ["_time"])
"""
    tables = query_api.query(flux, org=INFLUXDB_ORG)
    records = []
    for table in tables:
        for record in table.records:
            records.append({
                "time": record.get_time(),
                "value": record.get_value(),
                "measurement": record.get_measurement(),
            })
    # Sort by time across all tables (InfluxDB returns separate tables per _measurement)
    records.sort(key=lambda r: r["time"])
    return records


def find_outliers(records: list[dict], threshold: float) -> list[dict]:
    """Find outlier points where the value jumps abnormally compared to neighbors."""
    if len(records) < 3:
        return []

    outliers = []
    for i in range(1, len(records) - 1):
        prev_val = records[i - 1]["value"]
        curr_val = records[i]["value"]
        next_val = records[i + 1]["value"]

        if prev_val is None or curr_val is None or next_val is None:
            continue

        diff_from_prev = curr_val - prev_val
        diff_from_next = curr_val - next_val

        # Spike: big jump up from previous AND big drop to next
        is_spike = diff_from_prev > threshold and diff_from_next > threshold
        # Dip: big drop from previous AND big jump back to next
        is_dip = -diff_from_prev > threshold and -diff_from_next > threshold

        if is_spike or is_dip:
            outliers.append({
                "index": i,
                "time": records[i]["time"],
                "value": curr_val,
                "prev_value": prev_val,
                "next_value": next_val,
                "jump": abs(diff_from_prev),
                "type": "spike" if is_spike else "dip",
                "measurement": records[i]["measurement"],
            })

    # Also check first and last points
    if len(records) >= 2:
        # First point: outlier if far from second in either direction
        if records[0]["value"] is not None and records[1]["value"] is not None:
            diff = abs(records[0]["value"] - records[1]["value"])
            if diff > threshold:
                outliers.insert(0, {
                    "index": 0,
                    "time": records[0]["time"],
                    "value": records[0]["value"],
                    "prev_value": None,
                    "next_value": records[1]["value"],
                    "jump": diff,
                    "type": "spike" if records[0]["value"] > records[1]["value"] else "dip",
                    "measurement": records[0]["measurement"],
                })
        # Last point: outlier if far from second-to-last in either direction
        if records[-1]["value"] is not None and records[-2]["value"] is not None:
            diff = abs(records[-1]["value"] - records[-2]["value"])
            if diff > threshold:
                outliers.append({
                    "index": len(records) - 1,
                    "time": records[-1]["time"],
                    "value": records[-1]["value"],
                    "prev_value": records[-2]["value"],
                    "next_value": None,
                    "jump": diff,
                    "type": "spike" if records[-1]["value"] > records[-2]["value"] else "dip",
                    "measurement": records[-1]["measurement"],
                })

    return outliers


def delete_points(client: InfluxDBClient, entity_id: str, outliers: list[dict]) -> int:
    """Delete specific outlier data points from InfluxDB."""
    delete_api = client.delete_api()
    deleted = 0
    for outlier in outliers:
        ts: datetime = outlier["time"]
        # Use a 1-second window around the exact timestamp
        start = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        stop = ts.strftime("%Y-%m-%dT%H:%M:%S.999Z")
        predicate = f'entity_id="{entity_id}" AND _field="value"'

        try:
            delete_api.delete(
                start=start,
                stop=stop,
                predicate=predicate,
                bucket=BUCKET,
                org=INFLUXDB_ORG,
            )
            deleted += 1
            print(f"  Deleted: {ts.isoformat()} (value: {outlier['value']:.2f})")
        except Exception as e:
            print(f"  FAILED to delete {ts.isoformat()}: {e}")

    return deleted


def analyze_and_fix(
    client: InfluxDBClient, entity_id: str, apply: bool,
    range_start: str, range_stop: str, threshold: float,
    dump: int = 0,
) -> int:
    """Analyze one sensor and optionally fix outliers. Returns outlier count."""
    print(f"\n{'='*60}")
    print(f"Sensor: {entity_id}")
    print(f"{'='*60}")

    records = query_sensor_data(client, entity_id, range_start, range_stop)
    print(f"Data points in window: {len(records)}")

    # Count records per _measurement
    meas_counts: dict[str, int] = {}
    for r in records:
        m = r["measurement"]
        meas_counts[m] = meas_counts.get(m, 0) + 1
    if len(meas_counts) > 1:
        print(f"  WARNING: Multiple _measurement values: {meas_counts}")
    elif meas_counts:
        print(f"  _measurement: {list(meas_counts.keys())[0]}")

    if dump and records:
        n = min(dump, len(records))
        print(f"\n  First {n} data points:")
        for r in records[:n]:
            print(f"    {r['time'].isoformat()}  {r['value']:>12.2f}  ({r['measurement']})")
        if len(records) > n:
            print(f"  ... ({len(records) - n} more)")

    if not records:
        print("No data found. Check entity_id and date range.")
        return 0

    # Show value range
    values = [r["value"] for r in records if r["value"] is not None]
    if values:
        print(f"Value range: {min(values):.2f} – {max(values):.2f} kWh")

    outliers = find_outliers(records, threshold)

    if not outliers:
        print("No outliers found.")
        return 0

    print(f"\nFound {len(outliers)} outlier(s):")
    print(f"{'Timestamp':<30} {'Type':>6} {'Value':>12} {'Prev':>12} {'Next':>12} {'Jump':>12}")
    print("-" * 86)
    for o in outliers:
        prev_str = f"{o['prev_value']:.2f}" if o["prev_value"] is not None else "N/A"
        next_str = f"{o['next_value']:.2f}" if o["next_value"] is not None else "N/A"
        print(
            f"{o['time'].isoformat():<30} "
            f"{o['type']:>6} "
            f"{o['value']:>12.2f} "
            f"{prev_str:>12} "
            f"{next_str:>12} "
            f"{o['jump']:>12.2f}"
        )

    if apply:
        print(f"\nDeleting {len(outliers)} outlier point(s)...")
        deleted = delete_points(client, entity_id, outliers)
        print(f"Done. Deleted {deleted}/{len(outliers)} points.")
    else:
        print("\nDry run — no changes made. Use --apply to delete.")

    return len(outliers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix Shelly 3EM outliers in InfluxDB")
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete outlier points (default: dry run)",
    )
    parser.add_argument(
        "--threshold", type=float, default=OUTLIER_THRESHOLD_KWH,
        help=f"Jump threshold in kWh to consider a point an outlier (default: {OUTLIER_THRESHOLD_KWH})",
    )
    parser.add_argument(
        "--start", default=RANGE_START,
        help=f"Analysis window start (default: {RANGE_START})",
    )
    parser.add_argument(
        "--stop", default=RANGE_STOP,
        help=f"Analysis window stop (default: {RANGE_STOP})",
    )
    parser.add_argument(
        "--total-only", action="store_true",
        help="Only check the total sensor, skip per-phase sensors",
    )
    parser.add_argument(
        "--dump", type=int, metavar="N", default=0,
        help="Dump first N data points per sensor (for debugging)",
    )
    args = parser.parse_args()

    range_start = args.start
    range_stop = args.stop
    threshold = args.threshold

    if not INFLUXDB_TOKEN:
        print("ERROR: INFLUXDB_TOKEN not set. Check your .env file.", file=sys.stderr)
        sys.exit(1)

    print(f"InfluxDB: {INFLUXDB_URL}")
    print(f"Bucket:   {BUCKET}")
    print(f"Window:   {range_start} → {range_stop}")
    print(f"Threshold: {threshold} kWh")
    print(f"Mode:     {'APPLY (will delete!)' if args.apply else 'DRY RUN'}")

    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)

    try:
        total_outliers = 0

        # Check total energy sensor
        total_outliers += analyze_and_fix(
            client, ENTITY_ID, args.apply, range_start, range_stop, threshold, args.dump,
        )

        # Check per-phase sensors
        if not args.total_only:
            for phase_entity in PHASE_ENTITIES:
                total_outliers += analyze_and_fix(
                    client, phase_entity, args.apply, range_start, range_stop, threshold, args.dump,
                )

        print(f"\n{'='*60}")
        print(f"Total outliers found: {total_outliers}")
        if total_outliers > 0 and not args.apply:
            print("Re-run with --apply to delete them.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
