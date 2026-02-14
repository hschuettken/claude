"""Services health monitoring page."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState

# Service display metadata
SERVICE_META: dict[str, dict[str, str]] = {
    "pv-forecast": {"icon": "wb_sunny", "color": COLORS["solar"]},
    "smart-ev-charging": {"icon": "electric_car", "color": COLORS["ev"]},
    "ev-forecast": {"icon": "route", "color": COLORS["ev"]},
    "orchestrator": {"icon": "psychology", "color": COLORS["primary"]},
    "health-monitor": {"icon": "monitor_heart", "color": COLORS["grid_import"]},
    "dashboard": {"icon": "dashboard", "color": COLORS["primary"]},
}

DEFAULT_META = {"icon": "memory", "color": COLORS["text_muted"]}


def setup(state: DashboardState, settings: DashboardSettings) -> None:
    """Register the services page."""

    @ui.page("/services")
    def services_page() -> None:
        create_page_layout("/services")

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
            section_title("Service Health")

            @ui.refreshable
            def service_grid() -> None:
                if not state.services:
                    with ui.card().classes("w-full p-8"):
                        ui.label(
                            "No services detected yet. Waiting for MQTT heartbeats..."
                        ).style("color: #64748b")
                    return

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for name in sorted(state.services):
                        svc = state.services[name]
                        meta = SERVICE_META.get(name, DEFAULT_META)
                        _service_card(name, svc, meta)

            service_grid()

            # === Orchestrator activity ===
            @ui.refreshable
            def orchestrator_section() -> None:
                act = state.orchestrator_activity
                if not act:
                    return

                with ui.card().classes("w-full p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("psychology").style(f"color: {COLORS['primary']}")
                        ui.label("Orchestrator Activity").classes(
                            "text-lg font-bold"
                        ).style("color: #e2e8f0")

                    with ui.row().classes("w-full gap-8 flex-wrap"):
                        _stat_block(
                            "Messages Today", str(act.get("messages_today", 0))
                        )
                        _stat_block("Tool Calls", str(act.get("tools_today", 0)))
                        _stat_block(
                            "Suggestions", str(act.get("suggestions_today", 0))
                        )
                        if act.get("last_tool_name"):
                            _stat_block("Last Tool", act["last_tool_name"])

                    if act.get("last_decision"):
                        ui.separator().style("background: #2d2d4a")
                        ui.label("Last Decision").classes("text-xs uppercase mt-2").style(
                            "color: #64748b"
                        )
                        ui.label(act["last_decision"][:300]).classes(
                            "text-sm"
                        ).style("color: #94a3b8")

            orchestrator_section()

            ui.timer(
                settings.ui_refresh_interval,
                lambda: (service_grid.refresh(), orchestrator_section.refresh()),
            )


def _service_card(
    name: str, svc: dict, meta: dict[str, str],
) -> None:
    """Render a service health card."""
    status = svc.get("status", "unknown")
    is_online = status == "online"
    status_color = COLORS["online"] if is_online else COLORS["offline"]
    accent = meta["color"] if is_online else COLORS["text_dim"]

    uptime_s = svc.get("uptime_seconds", 0)
    uptime_str = _format_uptime(uptime_s)
    memory_mb = svc.get("memory_mb", 0)
    last_seen = svc.get("last_seen", 0)
    age = time.time() - last_seen if last_seen else 0
    age_str = f"{age:.0f}s ago" if age < 120 else f"{age / 60:.0f}m ago"

    with ui.card().classes("p-4 min-w-[250px] flex-1 metric-card").style(
        f"border-top: 3px solid {accent} !important"
    ):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("circle").style(
                f"color: {status_color}; font-size: 0.6rem"
            )
            ui.icon(meta["icon"]).style(f"color: {accent}")
            ui.label(name).classes("text-base font-bold").style("color: #e2e8f0")

        with ui.column().classes("gap-1"):
            _info_row("Status", status.capitalize(), status_color)
            _info_row("Uptime", uptime_str)
            if memory_mb > 0:
                _info_row("Memory", f"{memory_mb:.1f} MB")
            _info_row("Last seen", age_str)


def _info_row(label: str, value: str, value_color: str = "#e2e8f0") -> None:
    with ui.row().classes("items-center gap-2"):
        ui.label(label).classes("text-xs w-20").style("color: #64748b")
        ui.label(value).classes("text-sm").style(f"color: {value_color}")


def _stat_block(label: str, value: str) -> None:
    with ui.column().classes("gap-0"):
        ui.label(label).classes("text-xs uppercase").style("color: #64748b")
        ui.label(value).classes("text-lg font-bold").style("color: #e2e8f0")


def _format_uptime(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    hours = seconds / 3600
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"
