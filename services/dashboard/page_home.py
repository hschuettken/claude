"""Home / Energy overview page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from layout import COLORS, create_page_layout, metric_card, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState


def setup(state: DashboardState, settings: DashboardSettings) -> None:
    """Register the home page."""

    @ui.page("/")
    def home_page() -> None:
        create_page_layout("/")

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
            # === Energy metrics row ===
            section_title("Energy Overview")

            @ui.refreshable
            def energy_cards() -> None:
                pv = state.get_entity_float(settings.pv_power_entity)
                grid = state.get_entity_float(settings.grid_power_entity)
                bat_power = state.get_entity_float(settings.battery_power_entity)
                bat_soc = state.get_entity_float(settings.battery_soc_entity)
                house = state.get_entity_float(settings.house_power_entity)
                ev_power = state.get_entity_float(settings.ev_charge_power_entity)
                ev_soc = state.get_entity_float(settings.ev_soc_entity)

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    # PV
                    metric_card(
                        "wb_sunny",
                        "Solar PV",
                        f"{pv:,.0f}",
                        "W",
                        COLORS["solar"],
                    )

                    # Grid — positive = export, negative = import
                    if grid >= 0:
                        metric_card(
                            "north_east",
                            "Grid Export",
                            f"{grid:,.0f}",
                            "W",
                            COLORS["grid_export"],
                        )
                    else:
                        metric_card(
                            "south_west",
                            "Grid Import",
                            f"{abs(grid):,.0f}",
                            "W",
                            COLORS["grid_import"],
                        )

                    # Battery
                    if bat_power > 50:
                        bat_label = "Charging"
                    elif bat_power < -50:
                        bat_label = "Discharging"
                    else:
                        bat_label = "Idle"
                    metric_card(
                        "battery_charging_full",
                        f"Battery {bat_soc:.0f}%",
                        f"{abs(bat_power):,.0f}",
                        f"W \u00b7 {bat_label}",
                        COLORS["battery"],
                    )

                    # House
                    metric_card(
                        "home",
                        "House",
                        f"{house:,.0f}",
                        "W",
                        COLORS["house"],
                    )

                    # EV
                    ev_sub = f"SoC {ev_soc:.0f}%" if ev_soc > 0 else ""
                    metric_card(
                        "electric_car",
                        "EV Charging",
                        f"{ev_power:,.0f}",
                        "W",
                        COLORS["ev"],
                        subtitle=ev_sub,
                    )

            energy_cards()

            # === PV Forecast ===
            @ui.refreshable
            def pv_forecast_section() -> None:
                today = state.get_entity_float(settings.pv_forecast_today_entity)
                tomorrow = state.get_entity_float(settings.pv_forecast_tomorrow_entity)
                remaining = state.get_entity_float(settings.pv_forecast_remaining_entity)

                with ui.card().classes("w-full p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("wb_sunny").style(f"color: {COLORS['solar']}")
                        ui.label("PV Forecast").classes("text-lg font-bold").style(
                            "color: #e2e8f0"
                        )

                    with ui.row().classes("w-full gap-8"):
                        with ui.column().classes("gap-1"):
                            ui.label("Today").style("color: #94a3b8")
                            ui.label(f"{today:.1f} kWh").classes(
                                "text-2xl font-bold"
                            ).style(f"color: {COLORS['solar']}")
                            if remaining > 0:
                                ui.label(f"{remaining:.1f} kWh remaining").classes(
                                    "text-sm"
                                ).style("color: #64748b")

                        with ui.column().classes("gap-1"):
                            ui.label("Tomorrow").style("color: #94a3b8")
                            ui.label(f"{tomorrow:.1f} kWh").classes(
                                "text-2xl font-bold"
                            ).style(f"color: {COLORS['solar']}")

                    # Progress bar for today
                    if today > 0:
                        produced = today - remaining if remaining > 0 else today
                        progress = min(produced / today, 1.0) if today > 0 else 0
                        with ui.row().classes("w-full items-center gap-3 mt-4"):
                            ui.label("Progress").classes("text-sm").style(
                                "color: #64748b"
                            )
                            ui.linear_progress(
                                value=progress, show_value=False
                            ).props("rounded color=amber").classes("flex-1")
                            ui.label(f"{progress * 100:.0f}%").classes(
                                "text-sm font-bold"
                            ).style(f"color: {COLORS['solar']}")

            pv_forecast_section()

            # === EV Charging Status ===
            @ui.refreshable
            def ev_section() -> None:
                ev = state.ev_charging
                if not ev:
                    # Fall back to HA entities
                    mode = state.get_entity_state(settings.ev_charge_mode_entity)
                    soc = state.get_entity_float(settings.ev_soc_entity)
                    power = state.get_entity_float(settings.ev_charge_power_entity)
                    if mode == "unknown" and soc == 0 and power == 0:
                        return
                    ev = {
                        "charge_mode": mode,
                        "ev_soc_pct": soc,
                        "actual_power_w": power,
                    }

                with ui.card().classes("w-full p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("electric_car").style(f"color: {COLORS['ev']}")
                        ui.label("EV Charging").classes("text-lg font-bold").style(
                            "color: #e2e8f0"
                        )

                    with ui.row().classes("w-full gap-8 flex-wrap"):
                        _ev_stat("Mode", ev.get("charge_mode", "—"))
                        _ev_stat("Power", f"{ev.get('actual_power_w', 0):,.0f} W")
                        _ev_stat("SoC", f"{ev.get('ev_soc_pct', 0):.0f}%")
                        _ev_stat(
                            "Session", f"{ev.get('session_energy_kwh', 0):.1f} kWh"
                        )
                        if ev.get("pv_available_w") is not None:
                            _ev_stat("PV Available", f"{ev['pv_available_w']:,.0f} W")
                        if ev.get("status"):
                            _ev_stat("Status", ev["status"])

            ev_section()

            # === Services mini-overview ===
            @ui.refreshable
            def services_mini() -> None:
                with ui.card().classes("w-full p-4"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("dns").style(f"color: {COLORS['primary']}")
                        ui.label("Services").classes("text-lg font-bold").style(
                            "color: #e2e8f0"
                        )
                        ui.space()
                        online = sum(
                            1
                            for s in state.services.values()
                            if s.get("status") == "online"
                        )
                        total = len(state.services)
                        ui.label(f"{online}/{total} online").classes("text-sm").style(
                            "color: #94a3b8"
                        )

                    if not state.services:
                        ui.label("Waiting for service heartbeats...").style(
                            "color: #64748b"
                        )
                    else:
                        with ui.row().classes("gap-3 flex-wrap"):
                            for name in sorted(state.services):
                                svc = state.services[name]
                                status = svc.get("status", "unknown")
                                color = (
                                    COLORS["online"]
                                    if status == "online"
                                    else COLORS["offline"]
                                )
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("circle").style(
                                        f"color: {color}; font-size: 0.6rem"
                                    )
                                    ui.label(name).classes("text-sm").style(
                                        "color: #e2e8f0"
                                    )

            services_mini()

            # === Auto-refresh timer ===
            ui.timer(
                settings.ui_refresh_interval,
                lambda: (
                    energy_cards.refresh(),
                    pv_forecast_section.refresh(),
                    ev_section.refresh(),
                    services_mini.refresh(),
                ),
            )


def _ev_stat(label: str, value: str) -> None:
    """Render a small EV statistic."""
    with ui.column().classes("gap-0"):
        ui.label(label).classes("text-xs uppercase").style("color: #64748b")
        ui.label(value).classes("text-base font-semibold").style("color: #e2e8f0")
