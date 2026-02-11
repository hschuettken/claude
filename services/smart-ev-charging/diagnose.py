"""Diagnostic tool for smart-ev-charging service.

Run inside the container to test connectivity and data step by step,
instead of debugging the full running service.

Usage:
    docker compose run --rm smart-ev-charging python diagnose.py
    docker compose run --rm smart-ev-charging python diagnose.py --step ha
    docker compose run --rm smart-ev-charging python diagnose.py --step wallbox
    docker compose run --rm smart-ev-charging python diagnose.py --step energy
    docker compose run --rm smart-ev-charging python diagnose.py --step mqtt
    docker compose run --rm smart-ev-charging python diagnose.py --step cycle
    docker compose run --rm smart-ev-charging python diagnose.py --step all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
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


# -- Step: Config ──────────────────────────────────────────────

def check_config() -> dict:
    header("Configuration")
    try:
        from config import EVChargingSettings
        s = EVChargingSettings()
        result("Config loaded", True)

        checks = {
            "HA_URL": s.ha_url,
            "HA_TOKEN": s.ha_token[:8] + "..." if s.ha_token else "(empty)",
            "MQTT_HOST": s.mqtt_host,
            "WALLBOX_MAX_POWER_W": str(s.wallbox_max_power_w),
            "WALLBOX_MIN_POWER_W": str(s.wallbox_min_power_w),
            "ECO_CHARGE_POWER_W": str(s.eco_charge_power_w),
            "GRID_RESERVE_W": str(s.grid_reserve_w),
            "CONTROL_INTERVAL_SECONDS": str(s.control_interval_seconds),
            "BATTERY_MIN_SOC_PCT": str(s.battery_min_soc_pct),
            "BATTERY_EV_ASSIST_MAX_W": str(s.battery_ev_assist_max_w),
            "PV_FORECAST_GOOD_KWH": str(s.pv_forecast_good_kwh),
            "EV_SOC_ENTITY": s.ev_soc_entity or "(not configured)",
        }
        for key, val in checks.items():
            print(f"         {key} = {val}")

        if not s.ha_token:
            warn("HA_TOKEN is empty — HA connection will fail")
        if not s.ev_soc_entity:
            warn("EV_SOC_ENTITY not set — will use manual target energy")

        return {"settings": s}

    except Exception:
        result("Config loaded", False, traceback.format_exc())
        return {}


# -- Step: Home Assistant ──────────────────────────────────────

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
                   f"HA version: {config.get('version', '?')}")
        else:
            result("Config endpoint", False, f"Status: {resp.status_code}")

        # Test HA helpers
        for label, entity_id in [
            ("Charge mode selector", settings.charge_mode_entity),
            ("Full by morning toggle", settings.full_by_morning_entity),
            ("Departure time", settings.departure_time_entity),
            ("Target SoC", settings.target_soc_entity),
            ("Target energy", settings.target_energy_entity),
        ]:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                result(f"{label} ({entity_id})", True, f"Value: {val}")
            except Exception as e:
                result(f"{label} ({entity_id})", False, str(e))

    except Exception:
        result("API reachable", False, traceback.format_exc())
    finally:
        await ha.close()


# -- Step: Wallbox ─────────────────────────────────────────────

async def check_wallbox(settings) -> None:
    header("Wallbox (Amtron)")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        wallbox_entities = [
            ("Vehicle state", settings.wallbox_vehicle_state_entity),
            ("Power (W)", settings.wallbox_power_entity),
            ("Session energy (kWh)", settings.wallbox_energy_session_entity),
            ("HEMS power limit", settings.wallbox_hems_power_number),
        ]
        for label, entity_id in wallbox_entities:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                unit = state.get("attributes", {}).get("unit_of_measurement", "")
                result(f"{label} ({entity_id})", True, f"Value: {val} {unit}")
            except Exception as e:
                result(f"{label} ({entity_id})", False, str(e))

        # Test WallboxController
        info("Testing WallboxController...")
        from charger import WallboxController
        charger = WallboxController(
            ha=ha,
            vehicle_state_entity=settings.wallbox_vehicle_state_entity,
            power_entity=settings.wallbox_power_entity,
            energy_session_entity=settings.wallbox_energy_session_entity,
            hems_power_number=settings.wallbox_hems_power_number,
        )
        wb_state = await charger.read_state()
        result("WallboxController.read_state()", True,
               f"Vehicle: {wb_state.vehicle_state_text}\n"
               f"Connected: {wb_state.vehicle_connected}\n"
               f"Power: {wb_state.current_power_w} W\n"
               f"Session: {wb_state.session_energy_kwh} kWh")

    except Exception:
        result("Wallbox", False, traceback.format_exc())
    finally:
        await ha.close()


# -- Step: Energy State ────────────────────────────────────────

async def check_energy(settings) -> None:
    header("Energy State")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)

    async def read_val(entity_id: str) -> tuple[str, float | None]:
        try:
            state = await ha.get_state(entity_id)
            val = state.get("state", "?")
            if val in ("unavailable", "unknown"):
                return val, None
            return val, float(val)
        except Exception as e:
            return str(e), None

    try:
        entities = [
            ("Grid power", settings.grid_power_entity, "W", "positive=export, negative=import"),
            ("PV DC power", settings.pv_power_entity, "W", ""),
            ("House power", settings.house_power_entity, "W", "always positive"),
            ("Battery power", settings.battery_power_entity, "W", "positive=charging, negative=discharging"),
            ("Battery SoC", settings.battery_soc_entity, "%", ""),
            ("PV forecast remaining", settings.pv_forecast_remaining_entity, "kWh", ""),
        ]

        values: dict[str, float | None] = {}
        for label, entity_id, unit, note in entities:
            val_str, val_float = await read_val(entity_id)
            values[label] = val_float
            ok = val_float is not None
            detail = f"Value: {val_str} {unit}"
            if note:
                detail += f" ({note})"
            result(f"{label} ({entity_id})", ok, detail)

        # EV SoC (optional)
        if settings.ev_soc_entity:
            val_str, val_float = await read_val(settings.ev_soc_entity)
            values["EV SoC"] = val_float
            result(f"EV SoC ({settings.ev_soc_entity})",
                   val_float is not None, f"Value: {val_str} %")
        else:
            values["EV SoC"] = None
            info("EV SoC not configured (EV_SOC_ENTITY is empty)")

        # EV battery capacity + target SoC
        for label, entity_id in [
            ("EV battery capacity", settings.ev_battery_capacity_entity),
            ("EV target SoC", settings.target_soc_entity),
        ]:
            val_str, val_float = await read_val(entity_id)
            values[label] = val_float
            result(f"{label} ({entity_id})",
                   val_float is not None, f"Value: {val_str}")

        # Calculate PV surplus (same formula as the service)
        grid = values.get("Grid power") or 0
        pv = values.get("PV DC power") or 0
        battery = values.get("Battery power") or 0
        surplus = grid + battery - settings.grid_reserve_w
        info(f"PV surplus calculation:",
             f"grid ({grid:+.0f}) + battery ({battery:+.0f}) "
             f"- reserve ({settings.grid_reserve_w}) = {surplus:.0f} W\n"
             f"(EV would reclaim its own power when actually charging)")

        # SoC-based target
        ev_soc = values.get("EV SoC")
        ev_cap = values.get("EV battery capacity") or 77.0
        target_soc = values.get("EV target SoC") or 80.0
        if ev_soc is not None:
            needed = max(0, (target_soc - ev_soc) / 100.0 * ev_cap)
            info(
                "SoC-based target:",
                f"EV at {ev_soc:.0f}% → target {target_soc:.0f}%"
                f" × {ev_cap:.0f} kWh = {needed:.1f} kWh needed",
            )
        else:
            info("SoC-based target: N/A (no EV SoC sensor)")

    except Exception:
        result("Energy state", False, traceback.format_exc())
    finally:
        await ha.close()


# -- Step: MQTT ────────────────────────────────────────────────

def check_mqtt(settings) -> None:
    header("MQTT")
    import paho.mqtt.client as mqtt

    connected = False

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = (rc == 0)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="smart-ev-charging-diagnose",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
        client.loop_start()
        time.sleep(2)
        result("Connection", connected,
               f"{settings.mqtt_host}:{settings.mqtt_port}")

        if connected:
            pub_result = client.publish(
                "homelab/smart-ev-charging/diagnose",
                json.dumps({"test": True}),
            )
            result("Publish test", pub_result.rc == 0, "Topic: homelab/smart-ev-charging/diagnose")

        client.loop_stop()
        client.disconnect()
    except Exception:
        result("Connection", False, traceback.format_exc())


# -- Step: Control Cycle Dry Run ───────────────────────────────

async def check_cycle(settings) -> None:
    header("Control Cycle Dry Run")
    from datetime import datetime, time as dt_time
    from zoneinfo import ZoneInfo
    from shared.ha_client import HomeAssistantClient
    from charger import WallboxController
    from strategy import ChargeMode, ChargingContext, ChargingStrategy

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    tz = ZoneInfo(settings.timezone)

    try:
        charger = WallboxController(
            ha=ha,
            vehicle_state_entity=settings.wallbox_vehicle_state_entity,
            power_entity=settings.wallbox_power_entity,
            energy_session_entity=settings.wallbox_energy_session_entity,
            hems_power_number=settings.wallbox_hems_power_number,
        )
        strategy = ChargingStrategy(
            max_power_w=settings.wallbox_max_power_w,
            min_power_w=settings.wallbox_min_power_w,
            eco_power_w=settings.eco_charge_power_w,
            grid_reserve_w=settings.grid_reserve_w,
            start_hysteresis_w=settings.surplus_start_hysteresis_w,
            ramp_step_w=settings.ramp_step_w,
            battery_min_soc_pct=settings.battery_min_soc_pct,
            battery_ev_assist_max_w=settings.battery_ev_assist_max_w,
            pv_forecast_good_kwh=settings.pv_forecast_good_kwh,
        )

        async def read_float(entity_id: str, default: float = 0.0) -> float:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", str(default))
                if val in ("unavailable", "unknown"):
                    return default
                return float(val)
            except Exception:
                return default

        async def read_float_optional(entity_id: str) -> float | None:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "")
                if val in ("unavailable", "unknown", ""):
                    return None
                return float(val)
            except Exception:
                return None

        async def read_bool(entity_id: str) -> bool:
            try:
                state = await ha.get_state(entity_id)
                return state.get("state", "off") == "on"
            except Exception:
                return False

        async def read_time(entity_id: str) -> dt_time | None:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "")
                if not val or val in ("unavailable", "unknown"):
                    return dt_time(7, 0)
                parts = val.split(":")
                return dt_time(int(parts[0]), int(parts[1]))
            except Exception:
                return dt_time(7, 0)

        # Read all inputs
        mode_state = await ha.get_state(settings.charge_mode_entity)
        try:
            mode = ChargeMode(mode_state.get("state", "Off"))
        except (ValueError, KeyError):
            mode = ChargeMode.OFF

        wallbox = await charger.read_state()
        grid_power = await read_float(settings.grid_power_entity)
        pv_power = await read_float(settings.pv_power_entity)
        full_by_morning = await read_bool(settings.full_by_morning_entity)
        departure_time = await read_time(settings.departure_time_entity)
        target_energy = await read_float(settings.target_energy_entity)
        battery_power = await read_float(settings.battery_power_entity)
        battery_soc = await read_float(settings.battery_soc_entity)
        pv_forecast_remaining = await read_float(settings.pv_forecast_remaining_entity)
        ev_battery_cap = await read_float(settings.ev_battery_capacity_entity, 77.0)
        ev_target_soc = await read_float(settings.target_soc_entity, 80.0)

        ev_soc: float | None = None
        if settings.ev_soc_entity:
            ev_soc = await read_float_optional(settings.ev_soc_entity)

        ctx = ChargingContext(
            mode=mode,
            wallbox=wallbox,
            grid_power_w=grid_power,
            pv_power_w=pv_power,
            battery_power_w=battery_power,
            battery_soc_pct=battery_soc,
            pv_forecast_remaining_kwh=pv_forecast_remaining,
            full_by_morning=full_by_morning,
            departure_time=departure_time,
            target_energy_kwh=target_energy,
            session_energy_kwh=wallbox.session_energy_kwh,
            ev_soc_pct=ev_soc,
            ev_battery_capacity_kwh=ev_battery_cap,
            ev_target_soc_pct=ev_target_soc,
            now=datetime.now(tz),
        )

        decision = strategy.decide(ctx)

        ev_soc_str = f"{ev_soc:.0f}%" if ev_soc is not None else "N/A"
        result("Control cycle", True,
               f"Mode: {mode.value}\n"
               f"Vehicle: {wallbox.vehicle_state_text} (connected: {wallbox.vehicle_connected})\n"
               f"Grid: {grid_power:+.0f} W | PV: {pv_power:.0f} W\n"
               f"Battery: {battery_power:+.0f} W ({battery_soc:.0f}%)\n"
               f"EV SoC: {ev_soc_str} | Target SoC: {ev_target_soc:.0f}%"
               f" | Capacity: {ev_battery_cap:.0f} kWh\n"
               f"Energy needed: {ctx.energy_needed_kwh:.1f} kWh\n"
               f"PV forecast remaining: {pv_forecast_remaining:.1f} kWh\n"
               f"Full-by-morning: {full_by_morning} | "
               f"Target: {target_energy:.0f} kWh | "
               f"Departure: {departure_time}\n"
               f"--- Decision ---\n"
               f"Target power: {decision.target_power_w} W\n"
               f"PV surplus: {decision.pv_surplus_w:.0f} W\n"
               f"Battery assist: {decision.battery_assist_w:.0f} W ({decision.battery_assist_reason})\n"
               f"Reason: {decision.reason}")

        info("NOTE: This was a dry run — no HEMS limit was written to the wallbox.")

    except Exception:
        result("Control cycle", False, traceback.format_exc())
    finally:
        await ha.close()


# -- Main ──────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Smart EV Charging diagnostic tool")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "wallbox", "energy", "mqtt", "cycle", "all"],
        default="all",
        help="Which check to run (default: all)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  SMART EV CHARGING — DIAGNOSTIC TOOL")
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

    if args.step in ("all", "wallbox"):
        await check_wallbox(settings)

    if args.step in ("all", "energy"):
        await check_energy(settings)

    if args.step in ("all", "mqtt"):
        check_mqtt(settings)

    if args.step in ("all", "cycle"):
        await check_cycle(settings)

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
