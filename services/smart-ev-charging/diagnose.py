"""Diagnostic tool for smart-ev-charging service.

Run inside the container to test connectivity and sensor readings,
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
import traceback
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

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


# ── Step: Config ──────────────────────────────────────────────

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
            print(f"  [{WARN}] HA_TOKEN is empty — HA connection will fail")
        if not s.ev_soc_entity:
            print(f"  [{WARN}] EV_SOC_ENTITY not set — will use manual target energy")

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
            data = resp.json()
            result("Config endpoint", True, f"HA version: {data.get('version', '?')}")
        else:
            result("Config endpoint", False, f"Status: {resp.status_code}")

        # Check input helpers
        helpers = [
            ("Charge mode selector", settings.charge_mode_entity),
            ("Full by morning toggle", settings.full_by_morning_entity),
            ("Departure time", settings.departure_time_entity),
            ("Target SoC", settings.target_soc_entity),
            ("Target energy", settings.target_energy_entity),
        ]
        for label, entity_id in helpers:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                result(f"{label} ({entity_id})", True, f"Value: {val}")
            except Exception:
                result(f"{label} ({entity_id})", False, "Entity not found or unavailable")

    except Exception:
        result("HA connection", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Step: Wallbox ─────────────────────────────────────────────

async def check_wallbox(settings) -> None:
    header("Wallbox (Amtron)")
    from shared.ha_client import HomeAssistantClient
    from charger import WallboxController

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        entities = [
            ("Vehicle state", settings.wallbox_vehicle_state_entity, ""),
            ("Power (W)", settings.wallbox_power_entity, " W"),
            ("Session energy (kWh)", settings.wallbox_energy_session_entity, " kWh"),
            ("HEMS power limit", settings.wallbox_hems_power_number, ""),
        ]
        for label, entity_id, unit in entities:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                result(f"{label} ({entity_id})", True, f"Value: {val}{unit}")
            except Exception:
                result(f"{label} ({entity_id})", False, "Entity not found")

        info("Testing WallboxController...")
        ctrl = WallboxController(
            ha=ha,
            vehicle_state_entity=settings.wallbox_vehicle_state_entity,
            power_entity=settings.wallbox_power_entity,
            energy_session_entity=settings.wallbox_energy_session_entity,
            hems_power_number=settings.wallbox_hems_power_number,
        )
        wb = await ctrl.read_state()
        result(
            "WallboxController.read_state()", True,
            f"Vehicle: {wb.vehicle_state_text}\n"
            f"Connected: {wb.vehicle_connected}\n"
            f"Power: {wb.current_power_w} W\n"
            f"Session: {wb.session_energy_kwh} kWh",
        )

    except Exception:
        result("Wallbox check", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Step: Energy State ────────────────────────────────────────

async def check_energy(settings) -> dict:
    header("Energy State")
    from shared.ha_client import HomeAssistantClient

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    values = {}
    try:
        sensors = [
            ("Grid power", settings.grid_power_entity,
             "positive=export, negative=import"),
            ("PV DC power", settings.pv_power_entity, ""),
            ("House power", settings.house_power_entity, "always positive"),
            ("Battery power", settings.battery_power_entity,
             "positive=charging, negative=discharging"),
            ("Battery SoC", settings.battery_soc_entity, ""),
            ("PV forecast remaining", settings.pv_forecast_remaining_entity, ""),
        ]
        for label, entity_id, note in sensors:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                suffix = f" ({note})" if note else ""
                result(f"{label} ({entity_id})", True, f"Value: {val}{suffix}")
                try:
                    values[entity_id] = float(val)
                except (ValueError, TypeError):
                    pass
            except Exception:
                result(f"{label} ({entity_id})", False, "Entity not found")

        # EV SoC (optional)
        if settings.ev_soc_entity:
            try:
                state = await ha.get_state(settings.ev_soc_entity)
                val = state.get("state", "?")
                result(f"EV SoC ({settings.ev_soc_entity})", True, f"Value: {val} %")
                try:
                    values[settings.ev_soc_entity] = float(val)
                except (ValueError, TypeError):
                    pass
            except Exception:
                result(f"EV SoC ({settings.ev_soc_entity})", False, "Entity not found")
        else:
            info("EV SoC not configured (EV_SOC_ENTITY is empty)")

        # EV battery capacity + target SoC
        for label, entity_id in [
            ("EV battery capacity", settings.ev_battery_capacity_entity),
            ("EV target SoC", settings.target_soc_entity),
        ]:
            try:
                state = await ha.get_state(entity_id)
                val = state.get("state", "?")
                result(f"{label} ({entity_id})", True, f"Value: {val}")
                try:
                    values[entity_id] = float(val)
                except (ValueError, TypeError):
                    pass
            except Exception:
                result(f"{label} ({entity_id})", False, "Entity not found")

        # PV surplus calculation
        grid = values.get(settings.grid_power_entity, 0)
        bat = values.get(settings.battery_power_entity, 0)
        reserve = settings.grid_reserve_w
        surplus = grid + bat - reserve
        info(
            "PV surplus calculation:",
            f"grid ({grid:+.0f}) + battery ({bat:+.0f})"
            f" - reserve ({reserve}) = {surplus:.0f} W\n"
            f"(EV would reclaim its own power when actually charging)",
        )

        # SoC-based target
        ev_soc = values.get(settings.ev_soc_entity) if settings.ev_soc_entity else None
        ev_cap = values.get(settings.ev_battery_capacity_entity, 77.0)
        target_soc = values.get(settings.target_soc_entity, 80.0)
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

    return values


# ── Step: MQTT ────────────────────────────────────────────────

def check_mqtt(settings) -> None:
    header("MQTT")
    from shared.mqtt_client import MQTTClient

    try:
        mqtt = MQTTClient(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username or None,
            password=settings.mqtt_password or None,
        )
        mqtt.connect()
        result("Connection", True, f"{settings.mqtt_host}:{settings.mqtt_port}")

        mqtt.publish("homelab/smart-ev-charging/diagnose", {"test": True})
        result("Publish test", True, "Topic: homelab/smart-ev-charging/diagnose")

        mqtt.disconnect()
    except Exception:
        result("MQTT connection", False, traceback.format_exc())


# ── Step: Control Cycle Dry Run ───────────────────────────────

async def check_cycle(settings) -> None:
    header("Control Cycle Dry Run")
    from shared.ha_client import HomeAssistantClient
    from charger import WallboxController
    from strategy import ChargeMode, ChargingContext, ChargingStrategy

    ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
    try:
        ctrl = WallboxController(
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

        # Read everything
        wallbox = await ctrl.read_state()
        try:
            mode_state = await ha.get_state(settings.charge_mode_entity)
            mode = ChargeMode(mode_state.get("state", "Off"))
        except (ValueError, KeyError):
            mode = ChargeMode.OFF

        grid_power = await read_float(settings.grid_power_entity)
        pv_power = await read_float(settings.pv_power_entity)
        battery_power = await read_float(settings.battery_power_entity)
        battery_soc = await read_float(settings.battery_soc_entity)
        pv_forecast = await read_float(settings.pv_forecast_remaining_entity)
        target_energy = await read_float(settings.target_energy_entity)
        ev_battery_cap = await read_float(settings.ev_battery_capacity_entity, 77.0)
        ev_target_soc = await read_float(settings.target_soc_entity, 80.0)

        ev_soc: float | None = None
        if settings.ev_soc_entity:
            ev_soc = await read_float_optional(settings.ev_soc_entity)

        try:
            fbm_state = await ha.get_state(settings.full_by_morning_entity)
            full_by_morning = fbm_state.get("state", "off") == "on"
        except Exception:
            full_by_morning = False

        try:
            dep_state = await ha.get_state(settings.departure_time_entity)
            dep_val = dep_state.get("state", "07:00")
            parts = dep_val.split(":")
            departure_time = dt_time(int(parts[0]), int(parts[1]))
        except Exception:
            departure_time = dt_time(7, 0)

        tz = ZoneInfo(settings.timezone)
        ctx = ChargingContext(
            mode=mode,
            wallbox=wallbox,
            grid_power_w=grid_power,
            pv_power_w=pv_power,
            battery_power_w=battery_power,
            battery_soc_pct=battery_soc,
            pv_forecast_remaining_kwh=pv_forecast,
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

        # Calculate PV surplus for display
        pv_only = (
            grid_power + wallbox.current_power_w + battery_power
            - settings.grid_reserve_w
        )

        ev_soc_str = f"{ev_soc:.0f}%" if ev_soc is not None else "N/A"
        detail = (
            f"Mode: {mode.value}\n"
            f"Vehicle: {wallbox.vehicle_state_text}"
            f" (connected: {wallbox.vehicle_connected})\n"
            f"Grid: {grid_power:.0f} W | PV: {pv_power:.0f} W\n"
            f"Battery: {battery_power:+.0f} W ({battery_soc:.0f}%)\n"
            f"EV SoC: {ev_soc_str} | Target SoC: {ev_target_soc:.0f}%"
            f" | Capacity: {ev_battery_cap:.0f} kWh\n"
            f"Energy needed: {ctx.energy_needed_kwh:.1f} kWh\n"
            f"PV forecast remaining: {pv_forecast:.1f} kWh\n"
            f"Full-by-morning: {full_by_morning}"
            f" | Target: {target_energy:.0f} kWh"
            f" | Departure: {departure_time}\n"
            f"--- Decision ---\n"
            f"Target power: {decision.target_power_w} W\n"
            f"PV surplus: {pv_only:.0f} W\n"
            f"Reason: {decision.reason}"
        )
        result("Control cycle", True, detail)
        info("NOTE: This was a dry run — no HEMS limit was written to the wallbox.")

    except Exception:
        result("Control cycle", False, traceback.format_exc())
    finally:
        await ha.close()


# ── Main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Smart EV Charging diagnostics")
    parser.add_argument(
        "--step",
        choices=["config", "ha", "wallbox", "energy", "mqtt", "cycle", "all"],
        default="all",
        help="Which diagnostic step to run (default: all)",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("  SMART EV CHARGING — DIAGNOSTIC TOOL")
    print(f"{'='*60}")

    ctx = check_config()
    if not ctx:
        print("\nConfig failed — cannot continue.")
        sys.exit(1)

    settings = ctx["settings"]
    step = args.step

    if step in ("ha", "all"):
        asyncio.run(check_ha(settings))

    if step in ("wallbox", "all"):
        asyncio.run(check_wallbox(settings))

    if step in ("energy", "all"):
        asyncio.run(check_energy(settings))

    if step in ("mqtt", "all"):
        check_mqtt(settings)

    if step in ("cycle", "all"):
        asyncio.run(check_cycle(settings))

    header("DONE")


if __name__ == "__main__":
    import sys
    main()
