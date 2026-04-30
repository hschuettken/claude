"""NB9OS Vision dashboard page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState


_STATUS_COLOR: dict[str, str] = {
    "online": COLORS["online"],
    "offline": COLORS["offline"],
    "planned": COLORS["warning"],
    "unknown": COLORS["text_dim"],
}

_STATUS_ICON: dict[str, str] = {
    "online": "check_circle",
    "offline": "error",
    "planned": "pending",
    "unknown": "help",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /vision page."""

    base = settings.orchestrator_url

    async def _get_vision() -> dict[str, Any] | None:
        headers = {}
        if settings.orchestrator_api_key:
            headers["X-API-Key"] = settings.orchestrator_api_key

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}/api/v1/vision", headers=headers)
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    @ui.page("/vision")
    async def vision_page() -> None:
        create_page_layout("/vision")

        cache: dict[str, Any] = {"summary": await _get_vision()}

        async def _on_refresh() -> None:
            cache["summary"] = await _get_vision()
            render_summary.refresh()
            render_areas.refresh()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Vision")
                    ui.label("Home Brain north star and implementation map").style(
                        "color: #94a3b8"
                    )
                ui.button(
                    "Refresh",
                    icon="refresh",
                    on_click=_on_refresh,
                ).props("flat no-caps").style("color: #94a3b8")

            @ui.refreshable
            def render_summary() -> None:
                summary = cache["summary"]
                if not summary:
                    with ui.card().classes("w-full p-8"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon("cloud_off").classes("text-3xl").style(
                                f"color: {COLORS['offline']}"
                            )
                            with ui.column().classes("gap-1"):
                                ui.label("Vision API unavailable").classes(
                                    "text-lg font-bold"
                                ).style("color: #e2e8f0")
                                ui.label(
                                    "Waiting for orchestrator /api/v1/vision."
                                ).classes("text-sm").style("color: #94a3b8")
                    return

                areas = summary.get("areas", [])
                total = summary.get("areas_total", len(areas))
                online = summary.get("services_online", 0)
                planned = sum(1 for area in areas if area.get("status") == "planned")
                tracked = sum(1 for area in areas if area.get("service"))

                with ui.card().classes("w-full p-5").style(
                    f"border-left: 4px solid {COLORS['primary']} !important"
                ):
                    with ui.row().classes("items-start gap-4"):
                        ui.icon("visibility").classes("text-3xl").style(
                            f"color: {COLORS['primary']}"
                        )
                        with ui.column().classes("gap-3 flex-1"):
                            ui.label(summary.get("north_star", "")).classes(
                                "text-base"
                            ).style("color: #e2e8f0; line-height: 1.7")
                            with ui.row().classes("gap-3 flex-wrap"):
                                _pill("Areas", str(total), COLORS["primary"])
                                _pill("Tracked", str(tracked), COLORS["battery"])
                                _pill("Online", str(online), COLORS["online"])
                                _pill("Planned", str(planned), COLORS["warning"])

            render_summary()

            @ui.refreshable
            def render_areas() -> None:
                summary = cache["summary"] or {}
                areas = summary.get("areas") or []
                if not areas:
                    return

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Implementation Areas")
                    ui.label(f"{len(areas)} areas").classes("text-sm").style(
                        "color: #94a3b8"
                    )

                with ui.grid(columns=3).classes("w-full gap-4"):
                    for area in areas:
                        _area_card(area)

            render_areas()


def _pill(label: str, value: str, color: str) -> None:
    with ui.row().classes("items-center gap-2 px-3 py-2 rounded").style(
        f"background: {color}20; border: 1px solid {color}55"
    ):
        ui.label(value).classes("text-sm font-bold").style(f"color: {color}")
        ui.label(label).classes("text-xs uppercase").style("color: #94a3b8")


def _area_card(area: dict[str, Any]) -> None:
    status = area.get("status", "unknown")
    color = _STATUS_COLOR.get(status, COLORS["text_dim"])
    icon = _STATUS_ICON.get(status, "help")
    service = area.get("service")

    with ui.card().classes("p-4 min-h-[210px]").style(
        f"border-top: 3px solid {color} !important"
    ):
        with ui.row().classes("items-start gap-3 w-full no-wrap"):
            ui.label(str(area.get("id", ""))).classes(
                "text-2xl font-bold"
            ).style(f"color: {color}; min-width: 2rem")
            with ui.column().classes("gap-2 flex-1 min-w-0"):
                ui.label(area.get("title", "Untitled")).classes(
                    "text-base font-bold"
                ).style("color: #e2e8f0")
                ui.label(area.get("description", "")).classes("text-sm").style(
                    "color: #94a3b8; line-height: 1.55"
                )

        ui.space()
        with ui.row().classes("items-center gap-2 mt-3"):
            ui.icon(icon).style(f"color: {color}; font-size: 1rem")
            ui.badge(status).classes("text-xs").style(
                f"background: {color}20; color: {color}"
            )
            if service:
                ui.label(service).classes("text-xs").style("color: #64748b")
