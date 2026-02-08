#!/usr/bin/env python3
"""Export Home Assistant data to a structured Markdown file.

Fetches all entities, states, services, areas, and devices from Home Assistant
and writes a comprehensive reference document. Useful for AI assistants and
developers who need a complete picture of the smart home setup.

Dependencies: Python 3.10+ (stdlib only). Optionally `pip install websockets`
for area/device/entity registry data.

Usage:
    python scripts/ha-export.py                      # Uses .env for HA_URL/HA_TOKEN
    python scripts/ha-export.py -o custom-path.md    # Custom output path
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "HomeAssistant_config" / "ha_export.md"

# Domains ordered by typical relevance for smart-home overview
DOMAIN_ORDER = [
    "sensor", "binary_sensor", "light", "switch", "climate", "cover",
    "fan", "media_player", "camera", "lock", "alarm_control_panel",
    "vacuum", "water_heater", "humidifier",
    "automation", "script", "scene", "input_boolean", "input_number",
    "input_select", "input_text", "input_datetime", "input_button",
    "timer", "counter", "number", "select", "text", "button",
    "device_tracker", "person", "zone", "sun", "weather",
    "update", "tts", "notify",
]

# Key attributes worth showing for specific domains
DOMAIN_EXTRA_ATTRS: dict[str, list[str]] = {
    "input_number": ["min", "max", "step", "mode"],
    "input_select": ["options"],
    "climate": ["hvac_modes", "min_temp", "max_temp"],
    "cover": ["current_position"],
    "media_player": ["source_list"],
    "light": ["supported_color_modes"],
    "fan": ["preset_modes"],
    "number": ["min", "max", "step", "mode"],
    "select": ["options"],
}


# ---------------------------------------------------------------------------
# Config: read HA_URL / HA_TOKEN from environment or .env file
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Minimal .env loader — no external deps needed."""
    for candidate in [Path.cwd() / ".env", REPO_ROOT / ".env"]:
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                # Don't override already-set env vars
                if key not in os.environ:
                    os.environ[key] = value
            return


def _get_config() -> tuple[str, str]:
    """Return (ha_url, ha_token) from env, falling back to .env file."""
    _load_dotenv()
    ha_url = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
    ha_token = os.environ.get("HA_TOKEN", "")
    return ha_url, ha_token


# ---------------------------------------------------------------------------
# REST API helpers (stdlib only — no httpx needed)
# ---------------------------------------------------------------------------

def _ha_get(url: str, token: str, path: str) -> Any:
    """GET a Home Assistant REST API endpoint. Returns parsed JSON."""
    req = urllib.request.Request(
        f"{url}/api{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    # Allow self-signed certs (common in homelab setups)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# WebSocket registry fetcher (optional — needs `pip install websockets`)
# ---------------------------------------------------------------------------

async def _fetch_ws_registries(
    url: str, token: str,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch area, device, and entity registries via the HA WebSocket API."""
    if websockets is None:
        print("  ! websockets not installed (pip install websockets) — skipping registries")
        return {}

    ws_url = url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/api/websocket"

    registries: dict[str, list[dict[str, Any]]] = {}
    commands = {
        "areas": "config/area_registry/list",
        "devices": "config/device_registry/list",
        "entities": "config/entity_registry/list",
    }

    try:
        # Allow self-signed certs for wss://
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with websockets.connect(ws_url, close_timeout=10, ssl=ssl_ctx if ws_url.startswith("wss") else None) as ws:
            # Auth handshake
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected initial message: {msg.get('type')}")

            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") != "auth_ok":
                err = msg.get("message", "unknown error")
                raise RuntimeError(f"WebSocket auth failed: {err}")

            # Fetch each registry over the same connection
            for i, (name, cmd) in enumerate(commands.items(), start=1):
                await ws.send(json.dumps({"id": i, "type": cmd}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if resp.get("success"):
                    registries[name] = resp["result"]
                    print(f"    {name}: {len(resp['result'])} entries")
                else:
                    err_msg = resp.get("error", {}).get("message", "unknown")
                    print(f"    {name}: failed ({err_msg})")
                    registries[name] = []

    except Exception as exc:
        print(f"  ! WebSocket failed: {exc}")
        print("    Continuing with REST API data only (no area/device info)")

    return registries


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape pipe characters for Markdown table cells."""
    if not text:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _trunc(text: str, max_len: int = 60) -> str:
    """Truncate text, replacing newlines with spaces."""
    if not text:
        return ""
    text = str(text).replace("\n", " ")
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _fmt_extra_attrs(attrs: dict[str, Any], domain: str) -> str:
    """Format the domain-specific extra attributes for the table."""
    keys = DOMAIN_EXTRA_ATTRS.get(domain, [])
    if not keys:
        return ""
    parts: list[str] = []
    for k in keys:
        if k in attrs:
            val = attrs[k]
            if isinstance(val, list):
                items = ", ".join(str(v) for v in val[:8])
                if len(val) > 8:
                    items += f" (+{len(val) - 8})"
                parts.append(f"{k}=[{items}]")
            else:
                parts.append(f"{k}={val}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Lookup builders
# ---------------------------------------------------------------------------

class RegistryLookup:
    """Convenience lookups built from the WebSocket registry data."""

    def __init__(self, registries: dict[str, list[dict[str, Any]]]) -> None:
        self.area_map: dict[str, str] = {}
        for a in registries.get("areas", []):
            self.area_map[a.get("area_id", "")] = a.get("name", "")

        self.device_map: dict[str, dict[str, Any]] = {}
        for d in registries.get("devices", []):
            self.device_map[d["id"]] = d

        self.entity_meta: dict[str, dict[str, Any]] = {}
        for e in registries.get("entities", []):
            self.entity_meta[e["entity_id"]] = e

    def area_for(self, entity_id: str) -> str:
        meta = self.entity_meta.get(entity_id, {})
        # Entity-level area takes precedence
        area_id = meta.get("area_id")
        if area_id and area_id in self.area_map:
            return self.area_map[area_id]
        # Fall back to device-level area
        device_id = meta.get("device_id")
        if device_id and device_id in self.device_map:
            area_id = self.device_map[device_id].get("area_id")
            if area_id and area_id in self.area_map:
                return self.area_map[area_id]
        return ""

    def device_name_for(self, entity_id: str) -> str:
        meta = self.entity_meta.get(entity_id, {})
        device_id = meta.get("device_id")
        if device_id and device_id in self.device_map:
            dev = self.device_map[device_id]
            return dev.get("name_by_user") or dev.get("name") or ""
        return ""

    def platform_for(self, entity_id: str) -> str:
        return self.entity_meta.get(entity_id, {}).get("platform", "")

    def is_disabled(self, entity_id: str) -> bool:
        return self.entity_meta.get(entity_id, {}).get("disabled_by") is not None

    def is_hidden(self, entity_id: str) -> bool:
        return self.entity_meta.get(entity_id, {}).get("hidden_by") is not None


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def generate_markdown(
    config: dict[str, Any],
    states: list[dict[str, Any]],
    services: list[dict[str, Any]],
    registries: dict[str, list[dict[str, Any]]],
) -> str:
    reg = RegistryLookup(registries)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ----- Group entities by domain (skip disabled/hidden) -----
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in states:
        eid = s.get("entity_id", "")
        if reg.is_disabled(eid) or reg.is_hidden(eid):
            continue
        domain = eid.split(".")[0] if "." in eid else "unknown"
        by_domain[domain].append(s)

    all_domains = sorted(
        by_domain.keys(),
        key=lambda d: (DOMAIN_ORDER.index(d) if d in DOMAIN_ORDER else 999, d),
    )

    # ----- Entity counts per area -----
    area_counts: dict[str, int] = defaultdict(int)
    for s in states:
        area = reg.area_for(s["entity_id"])
        if area:
            area_counts[area] += 1

    total_entities = sum(len(v) for v in by_domain.values())
    total_svc = sum(len(s.get("services", {})) for s in services)

    lines: list[str] = []

    # ===== Header =====
    lines.append("# Home Assistant Data Export\n")
    lines.append(f"> **Generated**: {now}  ")
    lines.append(f"> **HA Version**: {config.get('version', '?')}  ")
    lines.append(f"> **Instance**: {config.get('location_name', 'Home')}  ")
    lat = config.get("latitude", "?")
    lon = config.get("longitude", "?")
    tz = config.get("time_zone", "?")
    lines.append(f"> **Location**: {lat}, {lon} ({tz})\n")

    # ===== Summary =====
    lines.append("## Summary\n")
    areas_list = registries.get("areas", [])
    devices_list = registries.get("devices", [])
    lines.append(f"- **{len(areas_list)}** areas")
    lines.append(f"- **{len(devices_list)}** devices")
    lines.append(f"- **{total_entities}** entities across **{len(all_domains)}** domains")
    lines.append(f"- **{total_svc}** services across **{len(services)}** domains\n")

    # ===== Areas =====
    if areas_list:
        lines.append("## Areas\n")
        lines.append("| Area | Entities |")
        lines.append("|------|----------|")
        for a in sorted(areas_list, key=lambda x: x.get("name", "")):
            name = a.get("name", "")
            lines.append(f"| {_esc(name)} | {area_counts.get(name, 0)} |")
        lines.append("")

    # ===== Entities by Domain =====
    lines.append("## Entities by Domain\n")

    # Domain index
    for domain in all_domains:
        lines.append(f"- [{domain}](#{domain}) ({len(by_domain[domain])})")
    lines.append("")

    for domain in all_domains:
        entities = by_domain[domain]
        entities.sort(key=lambda e: (reg.area_for(e["entity_id"]) or "zzz", e["entity_id"]))

        lines.append(f"### {domain}\n")
        lines.append(f"{len(entities)} entities\n")

        has_extra = domain in DOMAIN_EXTRA_ATTRS
        if has_extra:
            lines.append("| Entity ID | Name | State | Unit | Class | Area | Extra |")
            lines.append("|-----------|------|-------|------|-------|------|-------|")
        else:
            lines.append("| Entity ID | Name | State | Unit | Class | Area |")
            lines.append("|-----------|------|-------|------|-------|------|")

        for e in entities:
            eid = e["entity_id"]
            attrs = e.get("attributes", {})
            name = _esc(attrs.get("friendly_name", ""))
            state = _esc(_trunc(e.get("state", ""), 40))
            unit = _esc(attrs.get("unit_of_measurement", ""))
            dcls = attrs.get("device_class", "")
            area = _esc(reg.area_for(eid))

            if has_extra:
                extra = _esc(_trunc(_fmt_extra_attrs(attrs, domain), 80))
                lines.append(
                    f"| `{eid}` | {name} | {state} | {unit} | {dcls} | {area} | {extra} |"
                )
            else:
                lines.append(
                    f"| `{eid}` | {name} | {state} | {unit} | {dcls} | {area} |"
                )

        lines.append("")

    # ===== Services =====
    lines.append("## Available Services\n")

    for svc_domain in sorted(services, key=lambda s: s.get("domain", "")):
        domain = svc_domain.get("domain", "")
        svcs = svc_domain.get("services", {})
        if not svcs:
            continue

        lines.append(f"### {domain}\n")
        lines.append(f"{len(svcs)} services\n")
        lines.append("| Service | Description | Fields |")
        lines.append("|---------|-------------|--------|")

        for svc_name, svc_info in sorted(svcs.items()):
            desc = _esc(_trunc(svc_info.get("description", ""), 80))
            fields = svc_info.get("fields", {})
            field_names = ", ".join(sorted(fields.keys())[:10])
            if len(fields) > 10:
                field_names += f", … (+{len(fields) - 10})"
            lines.append(
                f"| `{domain}.{svc_name}` | {desc} | {_esc(field_names)} |"
            )

        lines.append("")

    # ===== Devices =====
    if devices_list:
        lines.append("## Devices\n")
        lines.append("| Device | Manufacturer | Model | Area |")
        lines.append("|--------|--------------|-------|------|")

        for d in sorted(devices_list, key=lambda x: (
            reg.area_map.get(x.get("area_id", ""), "zzz"),
            (x.get("name_by_user") or x.get("name") or "").lower(),
        )):
            name = _esc(d.get("name_by_user") or d.get("name") or "")
            if not name:
                continue
            manufacturer = _esc(d.get("manufacturer") or "")
            model = _esc(_trunc(d.get("model") or "", 40))
            area = _esc(reg.area_map.get(d.get("area_id", ""), ""))
            lines.append(f"| {name} | {manufacturer} | {model} | {area} |")

        lines.append("")

    # ===== Footer =====
    lines.append("---\n")
    lines.append(
        "*Regenerate this file with `python scripts/ha-export.py`*\n"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Home Assistant data to a structured Markdown file.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args()

    ha_url, ha_token = _get_config()

    if not ha_token:
        print(
            "Error: HA_TOKEN is not set.\n"
            "Set it in .env or pass as an environment variable."
        )
        sys.exit(1)

    try:
        print(f"Connecting to Home Assistant at {ha_url} …")

        # -- REST: config --
        print("  Fetching config …")
        try:
            config = _ha_get(ha_url, ha_token, "/config")
            print(f"    HA version {config.get('version', '?')}")
        except Exception as exc:
            print(f"    Failed: {exc}")
            config = {}

        # -- REST: states --
        print("  Fetching states …")
        states: list[dict[str, Any]] = _ha_get(ha_url, ha_token, "/states")
        print(f"    {len(states)} entities")

        # -- REST: services --
        print("  Fetching services …")
        services: list[dict[str, Any]] = _ha_get(ha_url, ha_token, "/services")
        total_svc = sum(len(s.get("services", {})) for s in services)
        print(f"    {total_svc} services across {len(services)} domains")

        # -- WebSocket: registries (optional) --
        print("  Fetching registries via WebSocket …")
        registries = await _fetch_ws_registries(ha_url, ha_token)

        # -- Generate Markdown --
        print("Generating Markdown …")
        md = generate_markdown(config, states, services, registries)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding="utf-8")

        size_kb = args.output.stat().st_size / 1024
        print(f"\nDone — {args.output.relative_to(REPO_ROOT)}  ({size_kb:.1f} KB)")

    except urllib.error.HTTPError as exc:
        print(f"\nError: HTTP {exc.code} from {ha_url}")
        if exc.code == 401:
            print("  Check that HA_TOKEN is a valid long-lived access token.")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\nError: Cannot reach {ha_url} — {exc.reason}")
        print("  Check that HA_URL is correct and Home Assistant is running.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
