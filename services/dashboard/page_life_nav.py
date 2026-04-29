"""Life Navigation System dashboard page.

Fetches data from the life-nav service (http://life-nav:8243) and renders:
  - Financial independence progress (net worth, FI target, years-to-FI)
  - Monte Carlo fan chart (p10/p50/p90 net-worth trajectories)
  - Goal tracking by life area with progress bars
  - Health metrics snapshot with VO2max trend chart
  - Career milestone timeline
  - Weekly review prompt
  - Opportunities This Week card
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState

_AREA_COLOR: dict[str, str] = {
    "career": "#6366f1",
    "health": "#22c55e",
    "finance": "#eab308",
    "relationships": "#ec4899",
    "learning": "#3b82f6",
    "leisure": "#f97316",
    "other": "#94a3b8",
}
_AREA_ICON: dict[str, str] = {
    "career": "work",
    "health": "fitness_center",
    "finance": "account_balance",
    "relationships": "people",
    "learning": "school",
    "leisure": "beach_access",
    "other": "star",
}
_CAREER_COLOR: dict[str, str] = {
    "planned": "#94a3b8",
    "in_progress": "#3b82f6",
    "achieved": "#22c55e",
    "missed": "#ef4444",
}


# ── Module-level UI helpers ───────────────────────────────────────────────────

def _metric_card(icon: str, title: str, value: str, unit: str, color: str) -> None:
    with ui.card().classes("p-4 flex-1 min-w-[170px]").style(
        f"border-left: 4px solid {color} !important"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon).style(f"color: {color}")
            ui.label(title).classes("text-xs uppercase tracking-wide").style(
                "color: #94a3b8"
            )
        ui.label(value).classes("text-3xl font-bold mt-1").style(f"color: {color}")
        if unit:
            ui.label(unit).classes("text-sm").style("color: #64748b")


def _fi_pill(label: str, age: float, color: str) -> None:
    with ui.element("div").classes("flex items-center gap-2").style(
        f"background: #1a1a2e; border: 1px solid {color}; "
        "border-radius: 8px; padding: 6px 12px"
    ):
        ui.icon("flag").classes("text-sm").style(f"color: {color}")
        ui.label(f"{label}: age {age:.0f}").classes("text-sm").style(
            f"color: {color}"
        )


def _empty_state(icon: str, msg: str) -> None:
    with ui.card().classes("w-full p-8 text-center"):
        ui.icon(icon).classes("text-5xl").style("color: #64748b")
        ui.label(msg).classes("mt-2 text-sm").style("color: #94a3b8")


# ── Page setup ────────────────────────────────────────────────────────────────

def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /life-nav page."""

    base = settings.life_nav_url

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(path: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(f"{base}{path}")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    async def _post(path: str, payload: dict) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}{path}", json=payload)
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        return None

    async def _put(path: str, payload: dict) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.put(f"{base}{path}", json=payload)
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        return None

    async def _delete(path: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.delete(f"{base}{path}")
                return r.status_code in (200, 204)
        except Exception:
            pass
        return False

    # ── Page ──────────────────────────────────────────────────────────────────

    @ui.page("/life-nav")
    async def life_nav_page() -> None:
        create_page_layout("/life-nav")

        # Per-session data cache (populated once on load, refreshed every 60 s)
        cache: dict[str, Any] = {
            "dashboard": {},
            "goals": [],
            "simulation_runs": [],
            "health_latest": {},
            "health_history": [],
            "career": [],
            "opportunities": [],
        }

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get("/api/v1/dashboard"),
                _get("/api/v1/goals"),
                _get("/api/v1/simulation/runs"),
                _get("/api/v1/health-metrics/latest"),
                _get("/api/v1/health-metrics"),
                _get("/api/v1/career"),
                _get("/api/v1/opportunities"),
            )
            cache["dashboard"] = results[0] or {}
            cache["goals"] = results[1] or []
            cache["simulation_runs"] = results[2] or []
            cache["health_latest"] = results[3] or {}
            cache["health_history"] = results[4] or []
            cache["career"] = results[5] or []
            cache["opportunities"] = results[6] or []

        # _on_refresh is defined before the refreshables — Python resolves
        # the refreshable names in the enclosing scope at call time, not here.
        async def _on_refresh() -> None:
            await _load_data()
            render_summary.refresh()
            render_fi_chart.refresh()
            render_goals.refresh()
            render_health.refresh()
            render_career.refresh()
            render_weekly_review.refresh()
            render_opportunities.refresh()

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # ── Header ────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Life Navigation")
                    ui.label("Goals · Finance · Health · Career").style(
                        "color: #94a3b8"
                    )
                with ui.row().classes("gap-2"):
                    async def _on_edit_model() -> None:
                        model_data = await _get("/api/v1/model") or {}
                        _open_model_dialog(model_data)

                    ui.button(
                        "Life Model",
                        icon="edit",
                        on_click=_on_edit_model,
                    ).props("flat no-caps").style("color: #94a3b8")
                    ui.button(
                        "Refresh",
                        icon="refresh",
                        on_click=_on_refresh,
                    ).props("flat no-caps").style("color: #6366f1")

            # ── Summary metric cards ───────────────────────────────────────
            @ui.refreshable
            def render_summary() -> None:
                dash = cache["dashboard"]
                nw = dash.get("current_net_worth")
                fi_pct = dash.get("fi_progress_pct")
                fi_age = dash.get("fi_age_p50")
                active = dash.get("active_goals", 0)

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    _metric_card(
                        "account_balance",
                        "Net Worth",
                        f"€ {nw:,.0f}" if nw is not None else "—",
                        "",
                        COLORS["solar"],
                    )
                    _metric_card(
                        "trending_up",
                        "FI Progress",
                        f"{fi_pct:.1f} %" if fi_pct is not None else "—",
                        "toward FI target",
                        COLORS["grid_export"],
                    )
                    _metric_card(
                        "flag",
                        "FI Age (median)",
                        f"{fi_age:.0f}" if fi_age is not None else "—",
                        "years old",
                        COLORS["primary"],
                    )
                    _metric_card(
                        "track_changes",
                        "Active Goals",
                        str(active),
                        "in progress",
                        COLORS["ev"],
                    )

            render_summary()

            # ── FI Fan Chart ──────────────────────────────────────────────
            @ui.refreshable
            def render_fi_chart() -> None:
                section_title("Net Worth Trajectory")
                runs = cache["simulation_runs"]

                if not runs:
                    _empty_state("show_chart", "No simulation data — run Monte Carlo below")
                    with ui.row().classes("justify-center mt-2"):
                        ui.button(
                            "Run Monte Carlo Simulation",
                            icon="play_arrow",
                            on_click=_run_simulation,
                        ).props("flat no-caps").style("color: #6366f1")
                    return

                latest = runs[0]
                traj = latest.get("trajectory", [])
                fi_p50 = latest.get("fi_age_p50")
                fi_p10 = latest.get("fi_age_p10")
                fi_p90 = latest.get("fi_age_p90")

                if not traj:
                    with ui.card().classes("w-full p-4 text-center"):
                        ui.label("Trajectory data missing — re-run simulation").style(
                            "color: #94a3b8"
                        )
                    return

                ages = [t["age"] for t in traj]
                p10 = [t["p10"] / 1_000 for t in traj]
                p50 = [t["p50"] / 1_000 for t in traj]
                p90 = [t["p90"] / 1_000 for t in traj]

                ui.chart({
                    "chart": {
                        "backgroundColor": "#1a1a2e",
                        "style": {"color": "#e2e8f0"},
                        "spacing": [20, 20, 20, 20],
                    },
                    "title": {"text": None},
                    "credits": {"enabled": False},
                    "xAxis": {
                        "categories": ages,
                        "title": {"text": "Age", "style": {"color": "#94a3b8"}},
                        "labels": {"style": {"color": "#94a3b8"}},
                        "lineColor": "#2d2d4a",
                        "tickColor": "#2d2d4a",
                    },
                    "yAxis": {
                        "title": {"text": "Net Worth (k€)", "style": {"color": "#94a3b8"}},
                        "labels": {"style": {"color": "#94a3b8"}},
                        "gridLineColor": "#2d2d4a",
                    },
                    "legend": {
                        "itemStyle": {"color": "#94a3b8"},
                        "itemHoverStyle": {"color": "#e2e8f0"},
                    },
                    "tooltip": {
                        "shared": True,
                        "valueDecimals": 0,
                        "valueSuffix": " k€",
                        "backgroundColor": "#1a1a2e",
                        "borderColor": "#2d2d4a",
                        "style": {"color": "#e2e8f0"},
                    },
                    "series": [
                        {
                            "name": "p10–p90 band",
                            "type": "arearange",
                            "data": list(zip(p10, p90)),
                            "color": "#6366f1",
                            "fillOpacity": 0.12,
                            "lineWidth": 0,
                            "enableMouseTracking": False,
                            "showInLegend": False,
                        },
                        {
                            "name": "Optimistic (p90)",
                            "type": "line",
                            "data": p90,
                            "color": "#22c55e",
                            "dashStyle": "ShortDash",
                            "lineWidth": 1,
                            "marker": {"enabled": False},
                        },
                        {
                            "name": "Median (p50)",
                            "type": "line",
                            "data": p50,
                            "color": "#6366f1",
                            "lineWidth": 2,
                            "marker": {"enabled": False},
                        },
                        {
                            "name": "Pessimistic (p10)",
                            "type": "line",
                            "data": p10,
                            "color": "#ef4444",
                            "dashStyle": "ShortDash",
                            "lineWidth": 1,
                            "marker": {"enabled": False},
                        },
                    ],
                }).classes("w-full").style("height: 320px")

                with ui.row().classes("gap-4 mt-2 flex-wrap items-center justify-between"):
                    with ui.row().classes("gap-4 flex-wrap"):
                        if fi_p10:
                            _fi_pill("Pessimistic FI", fi_p10, "#ef4444")
                        if fi_p50:
                            _fi_pill("Median FI", fi_p50, "#6366f1")
                        if fi_p90:
                            _fi_pill("Optimistic FI", fi_p90, "#22c55e")
                    run_at = (latest.get("run_at") or "")[:10]
                    scenario = latest.get("scenario_name", "baseline")
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f'"{scenario}" · {run_at}').classes("text-xs").style(
                            "color: #64748b"
                        )
                        ui.button(
                            "Re-run",
                            icon="refresh",
                            on_click=_run_simulation,
                        ).props("flat no-caps dense").style(
                            "color: #64748b; font-size: 0.7rem"
                        )

            render_fi_chart()

            # ── Orbit Goals ───────────────────────────────────────────────
            @ui.refreshable
            def render_goals() -> None:
                section_title("Orbit Goals")
                goals = cache["goals"]
                active = [g for g in goals if g.get("status") == "active"]
                completed = sum(1 for g in goals if g.get("status") == "completed")

                with ui.row().classes("w-full items-center justify-between mb-2"):
                    ui.label(
                        f"{len(active)} active · {completed} completed"
                    ).classes("text-sm").style("color: #94a3b8")
                    ui.button(
                        "Add Goal",
                        icon="add",
                        on_click=lambda: _open_goal_dialog(),
                    ).props("flat no-caps").style("color: #6366f1; font-size: 0.75rem")

                if not active:
                    _empty_state("track_changes", "No active goals — set your first orbit goal")
                    return

                by_area: dict[str, list] = {}
                for g in active:
                    by_area.setdefault(g.get("life_area", "other"), []).append(g)

                with ui.grid(columns=2).classes("w-full gap-4"):
                    for area, area_goals in sorted(by_area.items()):
                        color = _AREA_COLOR.get(area, "#94a3b8")
                        icon = _AREA_ICON.get(area, "star")
                        with ui.card().classes("p-4").style(
                            f"border-left: 4px solid {color} !important"
                        ):
                            with ui.row().classes("items-center gap-2 mb-3"):
                                ui.icon(icon).style(f"color: {color}")
                                ui.label(area.title()).classes(
                                    "text-sm uppercase tracking-wide font-bold"
                                ).style(f"color: {color}")
                            for g in area_goals:
                                pct = float(g.get("progress_pct", 0))
                                with ui.column().classes("w-full gap-1 mb-2"):
                                    with ui.row().classes(
                                        "w-full items-center justify-between"
                                    ):
                                        ui.label(g["title"]).classes(
                                            "text-sm font-semibold"
                                        ).style("color: #e2e8f0")
                                        ui.label(f"{pct:.0f}%").classes(
                                            "text-xs"
                                        ).style(f"color: {color}")
                                    with ui.element("div").classes("w-full").style(
                                        "background: #2d2d4a; height: 5px; "
                                        "border-radius: 3px"
                                    ):
                                        ui.element("div").style(
                                            f"width: {min(pct, 100):.0f}%; "
                                            f"height: 5px; background: {color}; "
                                            "border-radius: 3px; "
                                            "transition: width 0.3s ease"
                                        )
                                    td = g.get("target_date")
                                    if td:
                                        ui.label(f"→ {td}").classes(
                                            "text-xs"
                                        ).style("color: #64748b")

            render_goals()

            # ── Health Snapshot ────────────────────────────────────────────
            @ui.refreshable
            def render_health() -> None:
                section_title("Health Snapshot")
                latest = cache["health_latest"]
                history = cache["health_history"]

                with ui.row().classes("w-full items-center justify-between mb-2"):
                    ui.label("").style("color: #94a3b8")
                    ui.button(
                        "Log Metric",
                        icon="add",
                        on_click=lambda: _open_health_dialog(),
                    ).props("flat no-caps").style("color: #22c55e; font-size: 0.75rem")

                if not latest and not history:
                    _empty_state("monitor_heart", "No health data — log your first metric")
                    return

                weight = latest.get("weight_kg")
                vo2 = latest.get("vo2max_estimated")
                hr = latest.get("resting_hr")
                training = latest.get("training_hours_week")

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    if weight is not None:
                        _metric_card("scale", "Weight", f"{weight:.1f} kg", "", COLORS["house"])
                    if vo2 is not None:
                        _metric_card(
                            "directions_run", "VO2max", f"{vo2:.1f}", "ml/kg/min",
                            COLORS["grid_export"],
                        )
                    if hr is not None:
                        _metric_card(
                            "favorite", "Resting HR", f"{hr} bpm", "", COLORS["grid_import"],
                        )
                    if training is not None:
                        _metric_card(
                            "fitness_center", "Training", f"{training:.1f} h", "this week",
                            COLORS["battery"],
                        )

                vo2_pts = [
                    (h.get("measured_at", "")[:10], h.get("vo2max_estimated"))
                    for h in reversed(history[-12:])
                    if h.get("vo2max_estimated") is not None
                ]
                if len(vo2_pts) >= 2:
                    ui.chart({
                        "chart": {
                            "type": "line",
                            "backgroundColor": "#1a1a2e",
                            "spacing": [10, 10, 10, 10],
                        },
                        "title": {
                            "text": "VO2max Trend",
                            "style": {"color": "#e2e8f0", "fontSize": "13px"},
                        },
                        "credits": {"enabled": False},
                        "xAxis": {
                            "categories": [d for d, _ in vo2_pts],
                            "labels": {"style": {"color": "#94a3b8"}, "rotation": -30},
                            "lineColor": "#2d2d4a",
                        },
                        "yAxis": {
                            "title": {
                                "text": "ml/kg/min",
                                "style": {"color": "#94a3b8"},
                            },
                            "labels": {"style": {"color": "#94a3b8"}},
                            "gridLineColor": "#2d2d4a",
                        },
                        "legend": {"enabled": False},
                        "tooltip": {
                            "valueSuffix": " ml/kg/min",
                            "backgroundColor": "#1a1a2e",
                            "borderColor": "#2d2d4a",
                            "style": {"color": "#e2e8f0"},
                        },
                        "series": [{
                            "name": "VO2max",
                            "data": [v for _, v in vo2_pts],
                            "color": "#22c55e",
                            "lineWidth": 2,
                            "marker": {"radius": 4, "fillColor": "#22c55e"},
                        }],
                    }).classes("w-full mt-2").style("height: 200px")

            render_health()

            # ── Career Milestones ──────────────────────────────────────────
            @ui.refreshable
            def render_career() -> None:
                section_title("Career Milestones")
                milestones = cache["career"]
                achieved = sum(1 for m in milestones if m.get("status") == "achieved")

                with ui.row().classes("w-full items-center justify-between mb-2"):
                    ui.label(
                        f"{achieved} achieved / {len(milestones)} total"
                    ).classes("text-sm").style("color: #94a3b8")
                    ui.button(
                        "Add Milestone",
                        icon="add",
                        on_click=lambda: _open_career_dialog(),
                    ).props("flat no-caps").style("color: #6366f1; font-size: 0.75rem")

                if not milestones:
                    _empty_state("work", "No career milestones — plan your first")
                    return

                with ui.column().classes("w-full gap-2"):
                    for m in milestones:
                        status = m.get("status", "planned")
                        color = _CAREER_COLOR.get(status, "#94a3b8")
                        impact = int(m.get("impact_score", 5))
                        td = m.get("achieved_at") or m.get("target_date")

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 4px solid {color} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full"):
                                ui.icon(
                                    "check_circle"
                                    if status == "achieved"
                                    else "radio_button_unchecked"
                                ).style(f"color: {color}")
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(m["title"]).classes(
                                        "text-sm font-semibold"
                                    ).style("color: #e2e8f0")
                                    desc = m.get("description", "")
                                    if desc:
                                        ui.label(desc).classes("text-xs").style(
                                            "color: #94a3b8"
                                        )
                                    if td:
                                        ui.label(td).classes("text-xs mt-1").style(
                                            "color: #64748b"
                                        )
                                with ui.column().classes("items-end gap-1"):
                                    ui.badge(
                                        status.replace("_", " "),
                                        color="grey",
                                    ).classes("text-xs")
                                    # Impact stars (compact)
                                    stars = "★" * impact + "☆" * (10 - impact)
                                    ui.label(stars[:5]).classes("text-xs").style(
                                        f"color: {color}; letter-spacing: 1px"
                                    )

            render_career()

            # ── Weekly Review ──────────────────────────────────────────────
            @ui.refreshable
            def render_weekly_review() -> None:
                section_title("Weekly Review")
                dash = cache["dashboard"]
                days = dash.get("days_since_last_review")
                last_date = dash.get("last_weekly_review")

                if days is None:
                    icon, msg, color = (
                        "event_note",
                        "No weekly review yet — start your first!",
                        "#f59e0b",
                    )
                elif days == 0:
                    icon, msg, color = (
                        "check_circle",
                        "Weekly review done today!",
                        "#22c55e",
                    )
                elif days <= 7:
                    icon, msg, color = (
                        "event_available",
                        f"Last review {days} days ago ({last_date})",
                        "#22c55e",
                    )
                else:
                    icon, msg, color = (
                        "warning",
                        f"Overdue! Last review was {days} days ago",
                        "#ef4444",
                    )

                with ui.card().classes("w-full p-5"):
                    with ui.row().classes("items-center gap-4 w-full"):
                        ui.icon(icon).classes("text-3xl").style(f"color: {color}")
                        ui.label(msg).classes("flex-1 text-sm").style(
                            f"color: {color}"
                        )
                        ui.button(
                            "Write Review",
                            icon="edit_note",
                            on_click=lambda: _open_review_dialog(),
                        ).props("no-caps").style(
                            "background: #6366f1; color: white"
                        )

            render_weekly_review()

            # ── Opportunities This Week ────────────────────────────────────
            @ui.refreshable
            def render_opportunities() -> None:
                section_title("Opportunities This Week")
                opps = cache["opportunities"]

                with ui.row().classes("w-full items-center justify-between mb-2"):
                    ui.label(f"{len(opps)} items").classes("text-sm").style(
                        "color: #94a3b8"
                    )
                    ui.button(
                        "Add",
                        icon="add",
                        on_click=lambda: _open_opp_dialog(),
                    ).props("flat no-caps").style(
                        "color: #eab308; font-size: 0.75rem"
                    )

                if not opps:
                    _empty_state(
                        "lightbulb",
                        "No opportunities tracked — add items to explore",
                    )
                    return

                with ui.column().classes("w-full gap-3"):
                    for opp in opps:
                        cat = opp.get("category", "other")
                        score = float(opp.get("relevance_score", 0.5))
                        color = _AREA_COLOR.get(cat, "#94a3b8")
                        opp_id = opp.get("id", "")

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 4px solid {color} !important"
                        ):
                            with ui.row().classes("items-start gap-3 w-full"):
                                ui.icon(
                                    _AREA_ICON.get(cat, "lightbulb")
                                ).style(f"color: {color}")
                                with ui.column().classes("flex-1 gap-1"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(opp["title"]).classes(
                                            "text-sm font-semibold"
                                        ).style("color: #e2e8f0")
                                        ui.badge(cat, color="grey").classes("text-xs")
                                    desc = opp.get("description", "")
                                    if desc:
                                        ui.label(desc).classes("text-xs").style(
                                            "color: #94a3b8"
                                        )
                                    with ui.element("div").classes("w-full").style(
                                        "background: #2d2d4a; height: 3px; "
                                        "border-radius: 2px; margin-top: 4px"
                                    ):
                                        ui.element("div").style(
                                            f"width: {score * 100:.0f}%; "
                                            f"height: 3px; background: {color}; "
                                            "border-radius: 2px"
                                        )

                                async def _remove(oid: str = opp_id) -> None:
                                    await _delete(f"/api/v1/opportunities/{oid}")
                                    cache["opportunities"] = (
                                        await _get("/api/v1/opportunities") or []
                                    )
                                    render_opportunities.refresh()

                                ui.button(
                                    icon="close",
                                    on_click=_remove,
                                ).props("flat dense round").style("color: #64748b")

            render_opportunities()

            # ── Auto-refresh every 60 s ────────────────────────────────────
            ui.timer(60.0, _on_refresh)

        # ── Dialogs ────────────────────────────────────────────────────────
        # Defined after layout so all refreshable names are in scope.

        def _open_model_dialog(model_data: dict) -> None:
            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 500px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Life Model").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                nw_inp = ui.number(
                    label="Current Net Worth (€)",
                    value=model_data.get("current_net_worth"),
                    min=0,
                ).classes("w-full")
                income_inp = ui.number(
                    label="Monthly Income (€)",
                    value=model_data.get("monthly_income"),
                    min=0,
                ).classes("w-full")
                expenses_inp = ui.number(
                    label="Monthly Expenses (€)",
                    value=model_data.get("monthly_expenses"),
                    min=0,
                ).classes("w-full")
                fi_expense_inp = ui.number(
                    label="Target Monthly Expense at FI (€)",
                    value=model_data.get("target_fi_monthly_expense"),
                    min=0,
                ).classes("w-full")
                ret_age_inp = ui.number(
                    label="Target Retirement Age",
                    value=model_data.get("target_retirement_age"),
                    min=30,
                    max=100,
                    step=1,
                ).classes("w-full")
                birth_yr_inp = ui.number(
                    label="Birth Year",
                    value=model_data.get("birth_year"),
                    min=1950,
                    max=2010,
                    step=1,
                ).classes("w-full")

                async def _save() -> None:
                    payload: dict[str, Any] = {}
                    if nw_inp.value is not None:
                        payload["current_net_worth"] = float(nw_inp.value)
                    if income_inp.value is not None:
                        payload["monthly_income"] = float(income_inp.value)
                    if expenses_inp.value is not None:
                        payload["monthly_expenses"] = float(expenses_inp.value)
                    if fi_expense_inp.value is not None:
                        payload["target_fi_monthly_expense"] = float(
                            fi_expense_inp.value
                        )
                    if ret_age_inp.value is not None:
                        payload["target_retirement_age"] = int(ret_age_inp.value)
                    if birth_yr_inp.value is not None:
                        payload["birth_year"] = int(birth_yr_inp.value)
                    if payload:
                        await _put("/api/v1/model", payload)
                        await _load_data()
                        render_summary.refresh()
                        render_fi_chart.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Save", on_click=_save).props("no-caps").style(
                        "background: #6366f1; color: white"
                    )
            dlg.open()

        async def _run_simulation() -> None:
            await _post("/api/v1/simulation/run", {"scenario_name": "baseline"})
            results = await asyncio.gather(
                _get("/api/v1/simulation/runs"),
                _get("/api/v1/dashboard"),
            )
            cache["simulation_runs"] = results[0] or []
            cache["dashboard"] = results[1] or {}
            render_fi_chart.refresh()
            render_summary.refresh()

        def _open_goal_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 480px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Add Goal").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                title_inp = ui.input(label="Title").classes("w-full")
                desc_inp = ui.textarea(label="Description").classes("w-full")
                area_sel = ui.select(
                    [
                        "career",
                        "health",
                        "finance",
                        "relationships",
                        "learning",
                        "leisure",
                        "other",
                    ],
                    label="Life Area",
                    value="other",
                ).classes("w-full")
                target_inp = ui.input(label="Target Date (YYYY-MM-DD)").classes(
                    "w-full"
                )

                async def _save() -> None:
                    if not title_inp.value:
                        return
                    payload: dict[str, Any] = {
                        "title": title_inp.value.strip(),
                        "description": (desc_inp.value or "").strip(),
                        "life_area": area_sel.value,
                    }
                    if target_inp.value:
                        payload["target_date"] = target_inp.value.strip()
                    await _post("/api/v1/goals", payload)
                    results = await asyncio.gather(
                        _get("/api/v1/goals"),
                        _get("/api/v1/dashboard"),
                    )
                    cache["goals"] = results[0] or []
                    cache["dashboard"] = results[1] or {}
                    render_goals.refresh()
                    render_summary.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Save", on_click=_save).props("no-caps").style(
                        "background: #6366f1; color: white"
                    )
            dlg.open()

        def _open_health_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 400px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Log Health Metric").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                weight_inp = ui.number(label="Weight (kg)", min=30, max=200)
                vo2_inp = ui.number(
                    label="VO2max estimated (ml/kg/min)", min=20, max=90
                )
                hr_inp = ui.number(
                    label="Resting HR (bpm)", min=30, max=120, step=1
                )
                training_inp = ui.number(
                    label="Training hours this week", min=0, max=40
                )

                async def _save() -> None:
                    payload: dict[str, Any] = {"source": "manual"}
                    if weight_inp.value is not None:
                        payload["weight_kg"] = float(weight_inp.value)
                    if vo2_inp.value is not None:
                        payload["vo2max_estimated"] = float(vo2_inp.value)
                    if hr_inp.value is not None:
                        payload["resting_hr"] = int(hr_inp.value)
                    if training_inp.value is not None:
                        payload["training_hours_week"] = float(training_inp.value)
                    if len(payload) > 1:
                        await _post("/api/v1/health-metrics", payload)
                        results = await asyncio.gather(
                            _get("/api/v1/health-metrics/latest"),
                            _get("/api/v1/health-metrics"),
                        )
                        cache["health_latest"] = results[0] or {}
                        cache["health_history"] = results[1] or []
                        render_health.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Log", on_click=_save).props("no-caps").style(
                        "background: #22c55e; color: white"
                    )
            dlg.open()

        def _open_career_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 480px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Add Career Milestone").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                title_inp = ui.input(label="Title").classes("w-full")
                desc_inp = ui.textarea(label="Description").classes("w-full")
                target_inp = ui.input(label="Target Date (YYYY-MM-DD)").classes(
                    "w-full"
                )
                with ui.column().classes("w-full gap-0"):
                    ui.label("Impact Score (1–10)").classes("text-xs").style(
                        "color: #94a3b8"
                    )
                    impact_inp = ui.slider(
                        min=1, max=10, step=1, value=5
                    ).classes("w-full")

                async def _save() -> None:
                    if not title_inp.value:
                        return
                    payload: dict[str, Any] = {
                        "title": title_inp.value.strip(),
                        "description": (desc_inp.value or "").strip(),
                        "impact_score": int(impact_inp.value),
                    }
                    if target_inp.value:
                        payload["target_date"] = target_inp.value.strip()
                    await _post("/api/v1/career", payload)
                    cache["career"] = await _get("/api/v1/career") or []
                    render_career.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Save", on_click=_save).props("no-caps").style(
                        "background: #6366f1; color: white"
                    )
            dlg.open()

        def _open_review_dialog() -> None:
            today_date = date.today()
            monday = today_date - timedelta(days=today_date.weekday())

            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 560px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Weekly Review").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                ui.label(f"Week of {monday.isoformat()}").classes("text-sm").style(
                    "color: #94a3b8"
                )
                acc_inp = ui.textarea(
                    label="Accomplishments this week"
                ).classes("w-full")
                chal_inp = ui.textarea(label="Challenges faced").classes("w-full")
                learn_inp = ui.textarea(label="Key learnings").classes("w-full")
                focus_inp = ui.textarea(
                    label="Focus for next week"
                ).classes("w-full")
                with ui.row().classes("items-center gap-4"):
                    energy_inp = ui.slider(
                        min=1, max=10, step=1, value=7
                    ).classes("flex-1")
                    ui.label("Energy (1–10)").classes("text-xs").style(
                        "color: #94a3b8"
                    )
                with ui.row().classes("items-center gap-4"):
                    mood_inp = ui.slider(
                        min=1, max=10, step=1, value=7
                    ).classes("flex-1")
                    ui.label("Mood (1–10)").classes("text-xs").style(
                        "color: #94a3b8"
                    )

                async def _save() -> None:
                    payload = {
                        "week_start": monday.isoformat(),
                        "accomplishments": (acc_inp.value or "").strip(),
                        "challenges": (chal_inp.value or "").strip(),
                        "learnings": (learn_inp.value or "").strip(),
                        "next_week_focus": (focus_inp.value or "").strip(),
                        "energy_level": int(energy_inp.value),
                        "mood": int(mood_inp.value),
                    }
                    await _post("/api/v1/weekly-reviews", payload)
                    cache["dashboard"] = await _get("/api/v1/dashboard") or {}
                    render_weekly_review.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Submit", on_click=_save).props("no-caps").style(
                        "background: #6366f1; color: white"
                    )
            dlg.open()

        def _open_opp_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("p-6").style(
                "min-width: 480px; background: #1a1a2e; gap: 16px"
            ):
                ui.label("Add Opportunity").classes("text-lg font-bold").style(
                    "color: #e2e8f0"
                )
                title_inp = ui.input(label="Title").classes("w-full")
                desc_inp = ui.textarea(label="Description").classes("w-full")
                cat_sel = ui.select(
                    ["job", "travel", "investment", "learning", "health", "other"],
                    label="Category",
                    value="other",
                ).classes("w-full")
                url_inp = ui.input(label="URL (optional)").classes("w-full")
                with ui.column().classes("w-full gap-0"):
                    ui.label("Relevance (0–100)").classes("text-xs").style(
                        "color: #94a3b8"
                    )
                    relevance_inp = ui.slider(
                        min=0, max=100, step=5, value=50
                    ).classes("w-full")

                async def _save() -> None:
                    if not title_inp.value:
                        return
                    payload: dict[str, Any] = {
                        "title": title_inp.value.strip(),
                        "description": (desc_inp.value or "").strip(),
                        "category": cat_sel.value,
                        "relevance_score": relevance_inp.value / 100.0,
                    }
                    if url_inp.value:
                        payload["url"] = url_inp.value.strip()
                    await _post("/api/v1/opportunities", payload)
                    cache["opportunities"] = await _get("/api/v1/opportunities") or []
                    render_opportunities.refresh()
                    dlg.close()

                with ui.row().classes("gap-2 justify-end mt-2"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps").style(
                        "color: #94a3b8"
                    )
                    ui.button("Add", on_click=_save).props("no-caps").style(
                        "background: #eab308; color: #0a0a14"
                    )
            dlg.open()
