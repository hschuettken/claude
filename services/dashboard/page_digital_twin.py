"""Digital Twin page — Parallel Reality scenario comparison + room thermal map."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState

_SCENARIO_COLORS = {
    "A": "#94a3b8",  # baseline — slate
    "B": "#eab308",  # aggressive battery — yellow
    "C": "#22c55e",  # EV PV-only — green
    "D": "#f97316",  # pre-heat — orange
}

_SCENARIO_ICONS = {
    "A": "home",
    "B": "battery_charging_full",
    "C": "electric_car",
    "D": "thermostat",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /digital-twin page."""

    @ui.page("/digital-twin")
    async def digital_twin_page() -> None:
        create_page_layout("/digital-twin")

        with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6"):

            # ── Header ────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Digital Twin — Parallel Reality")
                    ui.label("24-hour energy scenario comparison").style(
                        "color: #94a3b8"
                    )

                async def _run_simulation() -> None:
                    try:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            await client.post(
                                f"{settings.digital_twin_url}/api/v1/simulate",
                                json={},
                            )
                    except Exception:
                        pass

                ui.button(
                    "Refresh Simulation",
                    icon="refresh",
                    on_click=_run_simulation,
                ).props("flat no-caps").style("color: #6366f1")

            # ── Recommendation banner ─────────────────────────────────────
            @ui.refreshable
            def render_recommendation() -> None:
                rec = state.digital_twin_recommendation
                if not rec:
                    return
                sid = rec.get("scenario_id", "?")
                name = rec.get("scenario_name", sid)
                savings = rec.get("savings_eur", 0)
                color = _SCENARIO_COLORS.get(sid, "#94a3b8")

                with ui.card().classes("w-full p-4").style(
                    f"border-left: 4px solid {color} !important"
                ):
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.icon("lightbulb").style(f"color: {color}")
                        with ui.column().classes("flex-1 gap-0"):
                            ui.label(
                                f"Auto-optimization: Scenario {sid} ({name}) saves "
                                f"{savings:.2f} € vs baseline"
                            ).classes("font-semibold").style(f"color: {color}")
                            actions = rec.get("actions", [])
                            if actions:
                                ui.label(
                                    actions[0].get("description", "")
                                ).classes("text-xs").style("color: #94a3b8")

                        async def _apply(scenario_id: str = sid) -> None:
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as client:
                                    await client.post(
                                        f"{settings.digital_twin_url}"
                                        f"/api/v1/optimize/apply/{scenario_id}"
                                    )
                            except Exception:
                                pass

                        ui.button("Apply", icon="check", on_click=_apply).props(
                            "flat no-caps"
                        ).style(f"color: {color}")

            render_recommendation()

            # ── Scenario cards ────────────────────────────────────────────
            @ui.refreshable
            def render_scenarios() -> None:
                sim = state.digital_twin_simulation
                scenarios = sim.get("scenarios", [])
                best_cost = sim.get("best_cost_id")
                best_suff = sim.get("best_sufficiency_id")
                savings = sim.get("savings_vs_baseline_eur")

                if not scenarios:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("hourglass_empty").classes("text-5xl").style(
                            "color: #64748b"
                        )
                        ui.label(
                            "No simulation data yet — click Refresh Simulation"
                        ).classes("mt-2").style("color: #94a3b8")
                    return

                if savings is not None and savings > 0.01:
                    with ui.card().classes("w-full p-4").style(
                        "border-left: 4px solid #22c55e !important"
                    ):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("savings").style("color: #22c55e")
                            ui.label(
                                f"Best scenario saves {savings:.2f} € vs baseline today"
                            ).classes("font-semibold").style("color: #22c55e")

                with ui.grid(columns=2).classes("w-full gap-4"):
                    for s in scenarios:
                        sid = s.get("scenario_id", "?")
                        color = _SCENARIO_COLORS.get(sid, "#94a3b8")
                        icon = _SCENARIO_ICONS.get(sid, "bolt")
                        label = s.get("label", sid)

                        badges: list[str] = []
                        if sid == best_cost:
                            badges.append("lowest cost")
                        if sid == best_suff:
                            badges.append("best sufficiency")

                        with ui.card().classes("p-5").style(
                            f"border-left: 4px solid {color} !important;"
                            "transition: transform 0.15s ease;"
                        ):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon(icon).style(f"color: {color}")
                                ui.label(f"Scenario {sid}").classes(
                                    "text-sm uppercase tracking-wide font-bold"
                                ).style(f"color: {color}")
                                for badge in badges:
                                    ui.badge(badge, color="green").classes("text-xs")

                            ui.label(label).classes(
                                "text-base font-semibold mb-3"
                            ).style("color: #e2e8f0")

                            with ui.grid(columns=2).classes("gap-y-2 gap-x-4"):
                                _kv("Energy cost", f"{s.get('energy_cost_eur', 0):.2f} €")
                                _kv(
                                    "Self-sufficiency",
                                    f"{s.get('self_sufficiency_pct', 0):.0f} %",
                                )
                                _kv(
                                    "EV charged",
                                    f"{s.get('ev_charged_kwh', 0):.1f} kWh",
                                )
                                _kv(
                                    "Comfort",
                                    f"{s.get('comfort_score', 0):.0f} / 100",
                                )
                                _kv(
                                    "Grid import",
                                    f"{s.get('grid_import_kwh', 0):.1f} kWh",
                                )
                                _kv(
                                    "Battery cycles",
                                    f"{s.get('battery_cycles', 0):.2f}",
                                )

            render_scenarios()

            # ── Thermal map ───────────────────────────────────────────────
            section_title("Room Thermal Map")

            @ui.refreshable
            def render_thermal_map() -> None:
                house = state.digital_twin_house_state
                rooms: dict[str, Any] = house.get("rooms", {})
                energy: dict[str, Any] = house.get("energy", {})

                if not rooms:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("device_thermostat").classes("text-5xl").style(
                            "color: #64748b"
                        )
                        ui.label(
                            "No room data — waiting for state refresh"
                        ).classes("mt-2").style("color: #94a3b8")
                    return

                # Energy summary strip
                if energy:
                    with ui.card().classes("w-full p-4"):
                        with ui.row().classes("gap-8 flex-wrap"):
                            pv_w = energy.get("pv_total_power_w", 0) or 0
                            bat_soc = energy.get("battery_soc_pct", 0) or 0
                            grid_w = energy.get("grid_power_w", 0) or 0
                            house_w = energy.get("house_consumption_w", 0) or 0

                            _strip(
                                "solar_power",
                                f"{pv_w / 1000:.1f} kW",
                                "PV",
                                COLORS["solar"],
                            )
                            _strip(
                                "home",
                                f"{house_w / 1000:.1f} kW",
                                "House",
                                COLORS["house"],
                            )
                            _strip(
                                "battery_std",
                                f"{bat_soc:.0f} %",
                                "Battery",
                                COLORS["battery"],
                            )
                            g_color = COLORS["grid_export"] if grid_w >= 0 else COLORS["grid_import"]
                            g_label = "Exporting" if grid_w >= 0 else "Importing"
                            _strip(
                                "power",
                                f"{abs(grid_w) / 1000:.1f} kW",
                                g_label,
                                g_color,
                            )

                with ui.grid(columns=3).classes("w-full gap-4 mt-2"):
                    for room_id, room in rooms.items():
                        temp = room.get("temperature_c")
                        humidity = room.get("humidity_pct")
                        occupied = room.get("occupied", False)
                        name = room.get(
                            "name", room_id.replace("_", " ").title()
                        )
                        color = _temp_to_color(temp)

                        with ui.card().classes("p-4").style(
                            f"border-left: 4px solid {color} !important"
                        ):
                            with ui.row().classes(
                                "items-center justify-between mb-1"
                            ):
                                ui.label(name).classes(
                                    "text-sm font-semibold"
                                ).style("color: #e2e8f0")
                                if occupied:
                                    ui.icon("person").classes("text-sm").style(
                                        "color: #22c55e"
                                    )

                            if temp is not None:
                                ui.label(f"{temp:.1f} °C").classes(
                                    "text-2xl font-bold"
                                ).style(f"color: {color}")
                            else:
                                ui.label("—").classes("text-2xl").style(
                                    "color: #64748b"
                                )

                            if humidity is not None:
                                ui.label(f"{humidity:.0f} % humidity").classes(
                                    "text-xs mt-1"
                                ).style("color: #64748b")

            render_thermal_map()

            # Auto-refresh every 30 s
            ui.timer(
                30.0,
                lambda: (
                    render_recommendation.refresh(),
                    render_scenarios.refresh(),
                    render_thermal_map.refresh(),
                ),
            )


# ── UI helpers ────────────────────────────────────────────────────────────────

def _kv(label: str, value: str) -> None:
    with ui.column().classes("gap-0"):
        ui.label(label).classes("text-xs").style("color: #64748b")
        ui.label(value).classes("text-sm font-semibold").style("color: #e2e8f0")


def _strip(icon: str, value: str, label: str, color: str) -> None:
    with ui.row().classes("items-center gap-1"):
        ui.icon(icon).classes("text-sm").style(f"color: {color}")
        ui.label(value).classes("text-sm font-semibold").style(f"color: {color}")
        ui.label(label).classes("text-xs").style("color: #64748b")


def _temp_to_color(temp: float | None) -> str:
    """Map temperature (°C) to a colour gradient: cold=blue → comfort=green → hot=red."""
    if temp is None:
        return "#64748b"
    if temp < 16:
        return "#3b82f6"   # cold — blue
    if temp < 20:
        return "#06b6d4"   # cool — cyan
    if temp < 23:
        return "#22c55e"   # comfortable — green
    if temp < 26:
        return "#f97316"   # warm — orange
    return "#ef4444"       # hot — red
