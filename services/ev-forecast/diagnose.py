"""Diagnostic tool for ev-forecast service.

Run inside the container to test connectivity and data step by step,
instead of debugging the full running service.

Usage:
    docker compose run --rm ev-forecast python diagnose.py
    docker compose run --rm ev-forecast python diagnose.py --step ha
    docker compose run --rm ev-forecast python diagnose.py --step audi
    docker compose run --rm ev-forecast python diagnose.py --step mqtt
    docker compose run --rm ev-forecast python diagnose.py --step calendar
    docker compose run --rm ev-forecast python diagnose.py --step geocoding
    docker compose run --rm ev-forecast python diagnose.py --step plan
    docker compose run --rm ev-forecast python diagnose.py --step all
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
        from config import EVForecastSettings
        s = EVForecastSettings()
        result("Config loaded", True)

        checks = {
            "HA_URL": s.ha_url,
            "HA_TOKEN": s.ha_token[:8] + "..." if s.ha_token else "(empty)",
            "MQTT_HOST": s.mqtt_host,
            "EV_BATTERY_CAPACITY_NET_KWH": str(s.ev_battery_capacity_net_kwh),
            "EV_CONSUMPTION_KWH_PER_100KM": str(s.ev_consumption_kwh_per_100km),
            "AUDI_ACCOUNT1_NAME": s.audi_account1_name,
            "AUDI_ACCOUNT1_SOC_ENTITY": s.audi_account1_soc_entity,
            "AUDI_ACCOUNT1_VIN": s.audi_account1_vin[:4] + "..." if s.audi_account1_vin else "(empty)",
            "AUDI_ACCOUNT2_NAME": s.audi_account2_name,
            "AUDI_ACCOUNT2_SOC_ENTITY": s.audi_account2_soc_entity,
            "AUDI_ACCOUNT2_VIN": s.audi_account2_vin[:4] + "..." if s.audi_account2_vin else "(empty)",
            "GOOGLE_CALENDAR_FAMILY_ID": s.google_calendar_family_id or "(not set)",
            "NICOLE_COMMUTE_KM": str(s.nicole_commute_km),
            "HANS_TRAIN_THRESHOLD_KM": str(s.hans_train_threshold_km),
            "HOME_LATITUDE": str(s.home_latitude),
            "HOME_LONGITUDE": str(s.home_longitude),
        }
        for key, val in checks.items():
            print(f"         {key} = {val}")

        if not s.ha_token:
            warn("HA_TOKEN is empty — HA connection will fail")
        if not s.audi_account1_vin and not s.audi_account2_vin:
            warn("No VINs configured — cloud refresh won't work")
        if not s.google_calendar_family_id:
            warn("No calendar ID — trip prediction from calendar will be skipped")

        # Show known destinations
        destinations = json.loads(s.known_destinations)
        info(f"Known destinations: {len(destinations)}", ", ".join(destinations.keys()))

        return {"settings": s}

    except Exception:
        result("Config loaded", False, traceback.format_exc())
        return {}


# ── Step: Home Assistant ──────────────────────────────────────

async def check_ha(settings) -> None:
    header("Home Assistant")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        client = await ha._get_client()
        resp = await client.get("/")
        result("API reachable", resp.status_code == 200, f"Status: {resp.status_code}")

        resp = await client.get("/config")
        if resp.status_code == 200:
            config = resp.json()
            result("Config endpoint", True,
                   f"HA version: {config.get('version', '?')}\n"
                   f"Location: {config.get('latitude', '?')}, {config.get('longitude', '?')}")
        else:
            result("Config endpoint", False, f"Status: {resp.status_code}")

        # Test HA helpers exist
        for label, entity in [
            ("Charge mode selector", settings.charge_mode_entity),
            ("Full by morning toggle", settings.full_by_morning_entity),
            ("Departure time", settings.departure_time_entity),
            ("Target energy", settings.target_energy_entity),
        ]:
            try:
                state = await ha.get_state(entity)
                val = state.get("state", "?")
                result(f"{label} ({entity})", True, f"Value: {val}")
            except Exception as e:
                result(f"{label} ({entity})", False, str(e))

    except Exception:
        result("API reachable", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Step: Audi Connect ────────────────────────────────────────

async def check_audi(settings) -> None:
    header("Audi Connect Sensors")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        for acct_name, entities in [
            (settings.audi_account1_name, {
                "SoC": settings.audi_account1_soc_entity,
                "Range": settings.audi_account1_range_entity,
                "Charging": settings.audi_account1_charging_entity,
                "Plug": settings.audi_account1_plug_entity,
                "Mileage": settings.audi_account1_mileage_entity,
            }),
            (settings.audi_account2_name, {
                "SoC": settings.audi_account2_soc_entity,
                "Range": settings.audi_account2_range_entity,
                "Charging": settings.audi_account2_charging_entity,
                "Plug": settings.audi_account2_plug_entity,
                "Mileage": settings.audi_account2_mileage_entity,
            }),
        ]:
            info(f"Account: {acct_name}")
            valid_count = 0
            for prop, entity_id in entities.items():
                try:
                    state = await ha.get_state(entity_id)
                    val = state.get("state", "?")
                    unit = state.get("attributes", {}).get("unit_of_measurement", "")
                    is_valid = val not in ("unknown", "unavailable", "None", "")
                    result(f"  {prop} ({entity_id})", is_valid, f"Value: {val} {unit}")
                    if is_valid:
                        valid_count += 1
                except Exception as e:
                    result(f"  {prop} ({entity_id})", False, str(e))

            if valid_count > 0:
                info(f"  -> {acct_name} has {valid_count}/{len(entities)} valid sensors")
            else:
                warn(f"  -> {acct_name} has NO valid sensors (probably not the active driver)")

        # Test vehicle monitor (dual account switching)
        info("Testing dual-account vehicle monitor...")
        from vehicle import AccountConfig, VehicleMonitor
        account1 = AccountConfig(
            name=settings.audi_account1_name,
            soc_entity=settings.audi_account1_soc_entity,
            range_entity=settings.audi_account1_range_entity,
            charging_entity=settings.audi_account1_charging_entity,
            plug_entity=settings.audi_account1_plug_entity,
            mileage_entity=settings.audi_account1_mileage_entity,
            remaining_charge_entity=settings.audi_account1_remaining_charge_entity,
            vin=settings.audi_account1_vin,
        )
        account2 = AccountConfig(
            name=settings.audi_account2_name,
            soc_entity=settings.audi_account2_soc_entity,
            range_entity=settings.audi_account2_range_entity,
            charging_entity=settings.audi_account2_charging_entity,
            plug_entity=settings.audi_account2_plug_entity,
            mileage_entity=settings.audi_account2_mileage_entity,
            remaining_charge_entity=settings.audi_account2_remaining_charge_entity,
            vin=settings.audi_account2_vin,
        )
        monitor = VehicleMonitor(ha, account1, account2, settings.ev_battery_capacity_net_kwh)
        state = await monitor.read_state()
        result("Vehicle monitor", state.is_valid,
               f"Active account: {state.active_account}\n"
               f"SoC: {state.soc_pct}%\n"
               f"Range: {state.range_km} km\n"
               f"Charging: {state.charging_state}\n"
               f"Plug: {state.plug_state}\n"
               f"Mileage: {state.mileage_km} km")

    except Exception:
        result("Audi Connect", False, traceback.format_exc())
    finally:
        await ha.close()


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

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="ev-forecast-diagnose",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        time.sleep(2)
        result("Connection", connected,
               f"{settings.mqtt_host}:{settings.mqtt_port}" +
               (f" — error: {error_msg}" if error_msg else ""))

        if connected:
            pub_result = client.publish(
                "homelab/ev-forecast/diagnose",
                json.dumps({"test": True}),
            )
            result("Publish test", pub_result.rc == 0, "Topic: homelab/ev-forecast/diagnose")

        client.loop_stop()
        client.disconnect()
    except Exception:
        result("Connection", False, traceback.format_exc())


# ── Step: Google Calendar ─────────────────────────────────────

async def check_calendar(settings) -> None:
    header("Google Calendar")
    from pathlib import Path

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        result("Google API library", True)
    except ImportError:
        result("Google API library", False, "pip install google-api-python-client google-auth")
        return

    if not settings.google_calendar_family_id:
        warn("GOOGLE_CALENDAR_FAMILY_ID not set — skipping")
        return

    try:
        import base64

        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds_file = settings.google_calendar_credentials_file
        creds_json = settings.google_calendar_credentials_json

        if creds_file and Path(creds_file).exists():
            creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
            result("Credentials loaded", True, f"From file: {creds_file}")
        elif creds_json:
            try:
                raw = base64.b64decode(creds_json)
                creds_info = json.loads(raw)
            except Exception:
                creds_info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
            result("Credentials loaded", True, "From JSON env var")
        else:
            result("Credentials loaded", False, "No credentials file or JSON configured")
            return

        service = build("calendar", "v3", credentials=creds)

        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.timezone)
        now = datetime.now(tz)
        time_max = (now + timedelta(days=settings.planning_horizon_days)).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId=settings.google_calendar_family_id,
                timeMin=now.isoformat(),
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )

        items = events_result.get("items", [])
        result("Calendar events", True,
               f"Found {len(items)} events in next {settings.planning_horizon_days} days")

        # Show driving-relevant events
        driving_count = 0
        for item in items:
            summary = item.get("summary", "")
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
            summary_lower = summary.lower()
            if summary_lower.startswith("h:") or summary_lower.startswith("n:"):
                driving_count += 1
                info(f"  Driving event: {summary}", f"Start: {start}")

        if driving_count == 0:
            info("  No driving events (H:/N: prefix) found in the next days")

    except Exception:
        result("Calendar API", False, traceback.format_exc())


# ── Step: Geocoding ───────────────────────────────────────────

async def check_geocoding(settings) -> None:
    header("Geocoding (Nominatim)")

    # Resolve home location
    lat = settings.home_latitude
    lon = settings.home_longitude
    if not lat or not lon:
        try:
            from shared.ha_client import HomeAssistantClient
            ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
            client = await ha._get_client()
            resp = await client.get("/config")
            config = resp.json()
            lat = config.get("latitude", 0.0)
            lon = config.get("longitude", 0.0)
            await ha.close()
            info(f"Home location from HA: {lat}, {lon}")
        except Exception:
            warn("Could not get home location — geocoding test will fail")
            return

    if not lat or not lon:
        warn("No home location available")
        return

    from trips import GeoDistance
    geo = GeoDistance(home_lat=lat, home_lon=lon, road_factor=settings.geocoding_road_factor)

    # Test with known cities
    test_cities = ["Bocholt", "Münster", "Aachen", "Stuttgart"]
    for city in test_cities:
        try:
            distance = await geo.estimate_distance(city)
            if distance is not None:
                result(f"Geocode '{city}'", True, f"Estimated road distance: {distance:.1f} km")
            else:
                result(f"Geocode '{city}'", False, "Geocoding returned no results")
        except Exception as e:
            result(f"Geocode '{city}'", False, str(e))


# ── Step: Plan dry run ────────────────────────────────────────

async def check_plan(settings) -> None:
    header("Plan Dry Run")
    from shared.ha_client import HomeAssistantClient
    from vehicle import AccountConfig, VehicleMonitor
    from trips import GeoDistance, TripPredictor
    from planner import ChargingPlanner

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)

    try:
        # Read vehicle state
        account1 = AccountConfig(
            name=settings.audi_account1_name,
            soc_entity=settings.audi_account1_soc_entity,
            range_entity=settings.audi_account1_range_entity,
            charging_entity=settings.audi_account1_charging_entity,
            plug_entity=settings.audi_account1_plug_entity,
            mileage_entity=settings.audi_account1_mileage_entity,
            remaining_charge_entity=settings.audi_account1_remaining_charge_entity,
            vin=settings.audi_account1_vin,
        )
        account2 = AccountConfig(
            name=settings.audi_account2_name,
            soc_entity=settings.audi_account2_soc_entity,
            range_entity=settings.audi_account2_range_entity,
            charging_entity=settings.audi_account2_charging_entity,
            plug_entity=settings.audi_account2_plug_entity,
            mileage_entity=settings.audi_account2_mileage_entity,
            remaining_charge_entity=settings.audi_account2_remaining_charge_entity,
            vin=settings.audi_account2_vin,
        )
        monitor = VehicleMonitor(ha, account1, account2, settings.ev_battery_capacity_net_kwh)
        vehicle = await monitor.read_state()
        info(f"Vehicle SoC: {vehicle.soc_pct}%, Range: {vehicle.range_km} km, Plug: {vehicle.plug_state}")

        # Resolve home location for geocoding
        lat = settings.home_latitude
        lon = settings.home_longitude
        if not lat or not lon:
            try:
                client = await ha._get_client()
                resp = await client.get("/config")
                config = resp.json()
                lat = config.get("latitude", 0.0)
                lon = config.get("longitude", 0.0)
            except Exception:
                pass

        geo = GeoDistance(lat, lon, settings.geocoding_road_factor) if lat and lon else None

        # Set up trip predictor
        known_destinations = json.loads(settings.known_destinations)
        commute_days = [d.strip() for d in settings.nicole_commute_days.split(",")]
        predictor = TripPredictor(
            known_destinations=known_destinations,
            consumption_kwh_per_100km=settings.ev_consumption_kwh_per_100km,
            nicole_commute_km=settings.nicole_commute_km,
            nicole_commute_days=commute_days,
            nicole_departure_time=settings.nicole_departure_time,
            nicole_arrival_time=settings.nicole_arrival_time,
            hans_train_threshold_km=settings.hans_train_threshold_km,
            timezone=settings.timezone,
            geo_distance=geo,
        )

        # Predict trips (using empty calendar for dry run)
        day_plans = await predictor.predict_trips([], days=settings.planning_horizon_days)

        for dp in day_plans:
            trip_list = ", ".join(t.label for t in dp.trips) or "no trips"
            info(f"  {dp.date}: {trip_list}")
            if dp.total_energy_kwh > 0:
                info(f"    Total energy: {dp.total_energy_kwh:.1f} kWh, "
                     f"Departure: {dp.earliest_departure}")

        # Generate plan
        planner = ChargingPlanner(
            ha=ha,
            net_capacity_kwh=settings.ev_battery_capacity_net_kwh,
            min_soc_pct=settings.min_soc_pct,
            buffer_soc_pct=settings.buffer_soc_pct,
            min_arrival_soc_pct=settings.min_arrival_soc_pct,
            timezone=settings.timezone,
        )
        plan = await planner.generate_plan(vehicle, day_plans)
        result("Plan generated", True,
               f"Current SoC: {plan.current_soc_pct}%\n"
               f"Vehicle plugged: {plan.vehicle_plugged_in}\n"
               f"Total energy needed: {plan.total_energy_needed_kwh:.1f} kWh")

        for day in plan.days:
            info(f"  {day.date}: [{day.urgency}] {day.charge_mode}",
                 f"Need: {day.energy_to_charge_kwh:.1f} kWh, "
                 f"Departure: {day.departure_time.strftime('%H:%M') if day.departure_time else 'none'}\n"
                 f"Reason: {day.reason}")

    except Exception:
        result("Plan", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Main ──────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="EV Forecast diagnostic tool")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "audi", "mqtt", "calendar", "geocoding", "plan", "all"],
        default="all",
        help="Which check to run (default: all)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  EV FORECAST — DIAGNOSTIC TOOL")
    print("=" * 60)

    ctx = check_config()
    settings = ctx.get("settings")
    if not settings:
        print("\n  Cannot proceed without valid config. Fix .env first.")
        sys.exit(1)

    if args.step in ("all", "config"):
        pass  # already ran above

    if args.step in ("all", "ha"):
        await check_ha(settings)

    if args.step in ("all", "audi"):
        await check_audi(settings)

    if args.step in ("all", "mqtt"):
        check_mqtt(settings)

    if args.step in ("all", "calendar"):
        await check_calendar(settings)

    if args.step in ("all", "geocoding"):
        await check_geocoding(settings)

    if args.step in ("all", "plan"):
        await check_plan(settings)

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
