"""Diagnostic tool for pv-forecast service.

Run inside the container to test connectivity and data step by step,
instead of debugging the full running service.

Usage:
    docker compose run --rm pv-forecast python diagnose.py
    docker compose run --rm pv-forecast python diagnose.py --step weather
    docker compose run --rm pv-forecast python diagnose.py --step influx
    docker compose run --rm pv-forecast python diagnose.py --step ha
    docker compose run --rm pv-forecast python diagnose.py --step mqtt
    docker compose run --rm pv-forecast python diagnose.py --step forecast
    docker compose run --rm pv-forecast python diagnose.py --step all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback

# Bootstrap shared library
from shared.log import setup_logging

setup_logging("DEBUG")


PASS = "\033[92m PASS \033[0m"
FAIL = "\033[91m FAIL \033[0m"
WARN = "\033[93m WARN \033[0m"
INFO = "\033[94m INFO \033[0m"


def header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def result(label: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    print(f"  [{status}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def info(label: str, detail: str = "") -> None:
    print(f"  [{INFO}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def warn(label: str, detail: str = "") -> None:
    print(f"  [{WARN}] {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


# ── Step: Config ──────────────────────────────────────────────

def check_config() -> dict:
    header("Configuration")
    try:
        from config import PVForecastSettings
        s = PVForecastSettings()
        result("Config loaded", True)

        # Check critical settings
        checks = {
            "HA_URL": s.ha_url,
            "HA_TOKEN": s.ha_token[:8] + "..." if s.ha_token else "(empty)",
            "INFLUXDB_URL": s.influxdb_url,
            "INFLUXDB_TOKEN": s.influxdb_token[:8] + "..." if s.influxdb_token else "(empty)",
            "INFLUXDB_BUCKET": s.influxdb_bucket,
            "MQTT_HOST": s.mqtt_host,
            "PV_EAST_ENERGY_ENTITY_ID": s.pv_east_energy_entity_id or "(not set)",
            "PV_EAST_CAPACITY_KWP": str(s.pv_east_capacity_kwp),
            "PV_WEST_ENERGY_ENTITY_ID": s.pv_west_energy_entity_id or "(not set)",
            "PV_WEST_CAPACITY_KWP": str(s.pv_west_capacity_kwp),
            "FORECAST_SOLAR_EAST_ENTITY_ID": s.forecast_solar_east_entity_id or "(not set)",
            "FORECAST_SOLAR_WEST_ENTITY_ID": s.forecast_solar_west_entity_id or "(not set)",
        }
        for key, val in checks.items():
            print(f"         {key} = {val}")

        if not s.ha_token:
            warn("HA_TOKEN is empty — HA connection will fail")
        if not s.influxdb_token:
            warn("INFLUXDB_TOKEN is empty — InfluxDB queries will fail")
        if not s.pv_east_energy_entity_id and not s.pv_west_energy_entity_id:
            warn("No PV entity IDs configured — model training will be skipped")

        return {"settings": s}

    except Exception as e:
        result("Config loaded", False, traceback.format_exc())
        return {}


# ── Step: Home Assistant ──────────────────────────────────────

async def check_ha(settings) -> None:
    header("Home Assistant")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        # Test API connectivity
        client = await ha._get_client()
        resp = await client.get("/")
        result("API reachable", resp.status_code == 200, f"Status: {resp.status_code}")

        # Test config endpoint (also gets location)
        resp = await client.get("/config")
        if resp.status_code == 200:
            config = resp.json()
            result("Config endpoint", True,
                   f"HA version: {config.get('version', '?')}\n"
                   f"Location: {config.get('latitude', '?')}, {config.get('longitude', '?')}")
        else:
            result("Config endpoint", False, f"Status: {resp.status_code}")

        # Test reading a PV entity (if configured)
        for label, entity_id in [
            ("East PV entity", settings.pv_east_energy_entity_id),
            ("West PV entity", settings.pv_west_energy_entity_id),
            ("Forecast.Solar East", settings.forecast_solar_east_entity_id),
            ("Forecast.Solar West", settings.forecast_solar_west_entity_id),
        ]:
            if not entity_id:
                info(f"{label}: not configured, skipping")
                continue
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                unit = state.get("attributes", {}).get("unit_of_measurement", "")
                result(f"{label} ({entity_id})", True, f"Value: {val} {unit}")
            except Exception as e:
                result(f"{label} ({entity_id})", False, str(e))

    except Exception as e:
        result("API reachable", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Step: InfluxDB ────────────────────────────────────────────

def check_influx(settings) -> None:
    header("InfluxDB")
    from shared.influx_client import InfluxClient

    influx = InfluxClient(settings.influxdb_url, settings.influxdb_token, settings.influxdb_org)
    try:
        # Test basic connectivity with a simple query
        tables = influx.query_raw(f'buckets() |> filter(fn: (r) => r.name == "{settings.influxdb_bucket}")')
        found = any(settings.influxdb_bucket in str(t) for t in tables)
        result("Connection", True, f"Bucket '{settings.influxdb_bucket}' found: {found}")

        # Test querying PV entities
        for label, entity_id in [
            ("East PV data", settings.pv_east_energy_entity_id),
            ("West PV data", settings.pv_west_energy_entity_id),
        ]:
            if not entity_id:
                info(f"{label}: not configured, skipping")
                continue
            try:
                records = influx.query_records(
                    bucket=settings.influxdb_bucket,
                    entity_id=entity_id,
                    range_start="-7d",
                )
                if records:
                    sample = records[0]
                    cols = list(sample.keys())
                    result(f"{label} ({entity_id})", True,
                           f"Records (7d): {len(records)}\n"
                           f"Columns: {cols}\n"
                           f"Sample value: {sample.get('_value', '?')} at {sample.get('_time', '?')}")
                else:
                    warn(f"{label} ({entity_id}): 0 records in last 7 days",
                         "Entity might not exist in InfluxDB or has a different name")
            except Exception as e:
                result(f"{label}", False, str(e))

    except Exception as e:
        result("Connection", False, traceback.format_exc())
    finally:
        influx.close()


# ── Step: MQTT ────────────────────────────────────────────────

def check_mqtt(settings) -> None:
    header("MQTT")
    import paho.mqtt.client as mqtt
    import time

    connected = False
    error_msg = ""

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = (rc == 0)

    def on_connect_fail(client, userdata):
        nonlocal error_msg
        error_msg = "Connection refused"

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="pv-forecast-diagnose",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        time.sleep(2)  # give it a moment
        result("Connection", connected,
               f"{settings.mqtt_host}:{settings.mqtt_port}" +
               (f" — error: {error_msg}" if error_msg else ""))

        if connected:
            # Test publish
            pub_result = client.publish("homelab/pv-forecast/diagnose", json.dumps({"test": True}))
            result("Publish test", pub_result.rc == 0, "Topic: homelab/pv-forecast/diagnose")

        client.loop_stop()
        client.disconnect()
    except Exception as e:
        result("Connection", False, traceback.format_exc())


# ── Step: Weather API ─────────────────────────────────────────

async def check_weather(settings) -> None:
    header("Open-Meteo Weather API")
    from weather import OpenMeteoClient

    lat = settings.pv_latitude
    lon = settings.pv_longitude

    # If location not set, try to get from HA
    if not lat or not lon:
        try:
            from shared.ha_client import HomeAssistantClient
            ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
            client = await ha._get_client()
            resp = await client.get("/config")
            config = resp.json()
            lat = config.get("latitude", 52.52)
            lon = config.get("longitude", 13.40)
            await ha.close()
            info(f"Location from HA: {lat}, {lon}")
        except Exception:
            lat, lon = 52.52, 13.40
            warn(f"Could not get location, using Berlin default: {lat}, {lon}")

    weather = OpenMeteoClient(lat, lon)
    try:
        records = await weather.get_solar_forecast(forecast_days=1)
        if records:
            daytime = [r for r in records if r.get("shortwave_radiation", 0) and r.get("shortwave_radiation", 0) > 0]
            result("Forecast API", True,
                   f"Hours returned: {len(records)}\n"
                   f"Daylight hours with radiation: {len(daytime)}\n"
                   f"Sample: {json.dumps({k: v for k, v in records[len(records)//2].items() if k != 'time'}, default=str, indent=2)[:300]}")
        else:
            result("Forecast API", False, "No records returned")
    except Exception as e:
        result("Forecast API", False, traceback.format_exc())
    finally:
        await weather.close()


# ── Step: Forecast dry run ────────────────────────────────────

async def check_forecast(settings) -> None:
    header("Forecast Dry Run")
    from weather import OpenMeteoClient
    from data import PVDataCollector
    from forecast import ForecastEngine
    from shared.ha_client import HomeAssistantClient
    from shared.influx_client import InfluxClient

    lat = settings.pv_latitude or 52.52
    lon = settings.pv_longitude or 13.40

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    influx = InfluxClient(settings.influxdb_url, settings.influxdb_token, settings.influxdb_org)
    weather = OpenMeteoClient(lat, lon)
    data_collector = PVDataCollector(influx, weather, settings)

    try:
        engine = ForecastEngine(settings, data_collector, weather, ha)

        # Try training
        info("Attempting model training...")
        train_results = await engine.train()
        for array, res in train_results.items():
            status = res.get("status", "?")
            if status == "trained":
                result(f"Train {array}", True,
                       f"R²={res.get('r2', '?')}, MAE={res.get('mae', '?')}, CV_R²={res.get('cv_r2', '?')}")
            elif status == "fallback":
                info(f"Train {array}: using fallback (only {res.get('days', 0)} days of data, need {settings.model_min_days})")
            else:
                warn(f"Train {array}: {status}")

        # Try forecasting
        info("Generating forecast...")
        forecast = await engine.forecast()
        result("Forecast generated", True,
               f"Today total: {forecast.today_total_kwh} kWh\n"
               f"Today remaining: {forecast.today_remaining_kwh} kWh\n"
               f"Tomorrow: {forecast.tomorrow_total_kwh} kWh\n"
               f"Day after: {forecast.day_after_total_kwh} kWh\n"
               f"East model: {forecast.east.model_type if forecast.east else 'none'}\n"
               f"West model: {forecast.west.model_type if forecast.west else 'none'}")

        # Show hourly breakdown for today
        for arr_name, arr in [("East", forecast.east), ("West", forecast.west)]:
            if arr and arr.today and arr.today.hourly:
                hours = [f"{h.time.strftime('%H:%M')}={h.kwh}" for h in arr.today.hourly]
                info(f"{arr_name} today hourly: {', '.join(hours)}")

    except Exception:
        result("Forecast", False, traceback.format_exc())
    finally:
        await ha.close()
        influx.close()
        await weather.close()


# ── Main ──────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="PV Forecast diagnostic tool")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "influx", "mqtt", "weather", "forecast", "all"],
        default="all",
        help="Which check to run (default: all)",
    )
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  PV FORECAST — DIAGNOSTIC TOOL")
    print("="*60)

    ctx = check_config()
    settings = ctx.get("settings")
    if not settings:
        print("\n  Cannot proceed without valid config. Fix .env first.")
        sys.exit(1)

    if args.step in ("all", "config"):
        pass  # already ran above

    if args.step in ("all", "ha"):
        await check_ha(settings)

    if args.step in ("all", "influx"):
        check_influx(settings)

    if args.step in ("all", "mqtt"):
        check_mqtt(settings)

    if args.step in ("all", "weather"):
        await check_weather(settings)

    if args.step in ("all", "forecast"):
        await check_forecast(settings)

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
