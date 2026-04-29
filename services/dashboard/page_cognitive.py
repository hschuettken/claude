"""Cognitive Layer dashboard page — External Brain v2 visualization.

Displays:
  - Daily briefing (LLM-generated narrative from cognitive-layer service)
  - Cognitive load score with breakdown (open threads, overdue tasks, events)
  - Knowledge Graph — Highcharts networkgraph of recent nodes + type legend
  - Thought threads (open / dormant) with recurrence badges
  - Ingestion trigger buttons (git, calendar, orbit)

Talks to the cognitive-layer service at settings.cognitive_layer_url (port 8230).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from config import DashboardSettings
    from state import DashboardState


_LOAD_COLOR: dict[str, str] = {
    "low": "#22c55e",
    "moderate": "#eab308",
    "high": "#f97316",
    "critical": "#ef4444",
}

_NODE_COLOR: dict[str, str] = {
    "git_commit": "#6366f1",
    "orbit_task": "#22c55e",
    "orbit_goal": "#eab308",
    "calendar_event": "#3b82f6",
    "meeting": "#a855f7",
    "chat": "#f97316",
    "thought": "#ec4899",
    "ha_event": "#94a3b8",
    "page": "#e2e8f0",
    "concept": "#64748b",
}

_NODE_ICON: dict[str, str] = {
    "git_commit": "commit",
    "orbit_task": "check_circle",
    "orbit_goal": "flag",
    "calendar_event": "event",
    "meeting": "groups",
    "chat": "chat_bubble",
    "thought": "psychology",
    "ha_event": "home",
    "page": "article",
    "concept": "hub",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /cognitive page."""

    base = settings.cognitive_layer_url

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(path: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}{path}")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    async def _post(path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base}{path}", params=params or {})
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        return None

    # ── Page ──────────────────────────────────────────────────────────────────

    @ui.page("/cognitive")
    async def cognitive_page() -> None:
        create_page_layout("/cognitive")

        cache: dict[str, Any] = {
            "briefing": None,
            "load": None,
            "nodes": [],
            "threads": [],
        }

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get("/api/v1/briefing"),
                _get("/api/v1/cognitive-load"),
                _get("/api/v1/nodes?limit=50"),
                _get("/api/v1/threads?status=open&limit=20"),
            )
            cache["briefing"] = results[0]
            cache["load"] = results[1]
            cache["nodes"] = results[2] or []
            cache["threads"] = results[3] or []

        async def _on_refresh() -> None:
            await _load_data()
            render_briefing.refresh()
            render_load.refresh()
            render_graph.refresh()
            render_threads.refresh()

        async def _trigger_ingest(source: str) -> None:
            params = {"days": 7} if source != "all" else {}
            await _post(f"/api/v1/ingest/{source}", params)
            await _on_refresh()

        async def _regen_briefing() -> None:
            await _post("/api/v1/briefing/regenerate")
            cache["briefing"] = await _get("/api/v1/briefing")
            render_briefing.refresh()

        async def _run_maintenance() -> None:
            await _post("/api/v1/threads/maintenance")
            cache["threads"] = await _get("/api/v1/threads?status=open&limit=20") or []
            render_threads.refresh()

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # ── Header ────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("External Brain")
                    ui.label(
                        "Knowledge Graph · Daily Briefing · Thought Threads · Cognitive Load"
                    ).style("color: #94a3b8")
                with ui.row().classes("gap-2 flex-wrap"):
                    ui.button(
                        "Ingest Git",
                        icon="commit",
                        on_click=lambda: asyncio.create_task(_trigger_ingest("git")),
                    ).props("flat no-caps dense").style(
                        "color: #6366f1; font-size: 0.75rem"
                    )
                    ui.button(
                        "Ingest Calendar",
                        icon="event",
                        on_click=lambda: asyncio.create_task(
                            _trigger_ingest("calendar")
                        ),
                    ).props("flat no-caps dense").style(
                        "color: #3b82f6; font-size: 0.75rem"
                    )
                    ui.button(
                        "Ingest Orbit",
                        icon="track_changes",
                        on_click=lambda: asyncio.create_task(
                            _trigger_ingest("orbit")
                        ),
                    ).props("flat no-caps dense").style(
                        "color: #22c55e; font-size: 0.75rem"
                    )
                    ui.button(
                        "Refresh",
                        icon="refresh",
                        on_click=_on_refresh,
                    ).props("flat no-caps").style("color: #94a3b8")

            # ── Briefing + Cognitive Load row ──────────────────────────────
            with ui.row().classes("w-full gap-4 items-start"):

                @ui.refreshable
                def render_briefing() -> None:
                    b = cache["briefing"]
                    with ui.card().classes("flex-1 p-5").style("min-width: 300px"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("wb_sunny").style("color: #eab308")
                            ui.label("Daily Briefing").classes(
                                "font-bold"
                            ).style("color: #e2e8f0")
                            if b:
                                ui.label(
                                    b.get("date", "")
                                ).classes("text-xs ml-auto").style(
                                    "color: #64748b"
                                )
                        if b and b.get("narrative"):
                            ui.label(b["narrative"]).classes("text-sm").style(
                                "color: #94a3b8; white-space: pre-wrap; "
                                "line-height: 1.7; max-height: 260px; "
                                "overflow-y: auto"
                            )
                        else:
                            ui.icon("schedule").classes("text-3xl mb-2").style(
                                "color: #64748b"
                            )
                            ui.label(
                                "No briefing yet — generated at 06:00 daily"
                            ).classes("text-sm").style("color: #64748b")
                            ui.button(
                                "Generate Now",
                                icon="play_arrow",
                                on_click=lambda: asyncio.create_task(
                                    _regen_briefing()
                                ),
                            ).props("flat no-caps dense").style(
                                "color: #eab308; margin-top: 8px"
                            )

                render_briefing()

                @ui.refreshable
                def render_load() -> None:
                    load = cache["load"]
                    score = float(load.get("debt_score", 0)) if load else 0.0
                    label = load.get("label", "low") if load else "low"
                    color = _LOAD_COLOR.get(label, "#94a3b8")
                    open_t = load.get("open_threads", 0) if load else 0
                    overdue = load.get("overdue_tasks", 0) if load else 0
                    unproc = load.get("unprocessed_events", 0) if load else 0

                    with ui.card().classes("p-5").style("min-width: 260px"):
                        with ui.row().classes("items-center gap-2 mb-4"):
                            ui.icon("psychology").style(f"color: {color}")
                            ui.label("Cognitive Load").classes(
                                "font-bold"
                            ).style("color: #e2e8f0")

                        with ui.row().classes("items-center gap-4 mb-4"):
                            with ui.column().classes("items-center"):
                                ui.label(f"{score:.0f}").classes(
                                    "text-5xl font-bold"
                                ).style(f"color: {color}")
                                ui.label("/ 100").classes("text-sm").style(
                                    "color: #64748b"
                                )
                            with ui.column().classes("gap-1"):
                                ui.badge(label).classes("text-sm px-3 py-1")
                                with ui.element("div").style(
                                    "background: #2d2d4a; height: 6px; "
                                    "width: 100px; border-radius: 3px; "
                                    "margin-top: 4px"
                                ):
                                    ui.element("div").style(
                                        f"width: {min(score, 100):.0f}%; "
                                        f"height: 6px; background: {color}; "
                                        "border-radius: 3px; "
                                        "transition: width 0.4s ease"
                                    )

                        with ui.grid(columns=3).classes("w-full gap-2"):
                            for icon_name, lbl, val, clr in [
                                ("format_list_bulleted", "Threads", open_t, COLORS["primary"]),
                                ("assignment_late", "Overdue", overdue, COLORS["grid_import"]),
                                ("bolt", "Events", unproc, COLORS["text_muted"]),
                            ]:
                                with ui.card().classes("p-2 text-center"):
                                    ui.icon(icon_name).classes("text-base").style(
                                        f"color: {clr}"
                                    )
                                    ui.label(str(val)).classes(
                                        "text-xl font-bold"
                                    ).style(f"color: {clr}")
                                    ui.label(lbl).classes("text-xs").style(
                                        "color: #64748b"
                                    )

                render_load()

            # ── Knowledge Graph ────────────────────────────────────────────
            @ui.refreshable
            def render_graph() -> None:
                section_title("Knowledge Graph")
                nodes = cache["nodes"]

                if not nodes:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("hub").classes("text-5xl").style(
                            "color: #64748b"
                        )
                        ui.label(
                            "No nodes yet — use the ingest buttons above to "
                            "populate the graph"
                        ).classes("mt-2 text-sm").style("color: #94a3b8")
                    return

                # Node-type legend
                by_type: dict[str, int] = {}
                for n in nodes:
                    by_type[n["node_type"]] = by_type.get(n["node_type"], 0) + 1

                with ui.row().classes("w-full gap-2 flex-wrap mb-3"):
                    for ntype, cnt in sorted(by_type.items()):
                        clr = _NODE_COLOR.get(ntype, "#94a3b8")
                        with ui.element("div").classes(
                            "flex items-center gap-1 px-2 py-1"
                        ).style(
                            f"background: #1a1a2e; border: 1px solid {clr}; "
                            "border-radius: 999px"
                        ):
                            ui.element("div").style(
                                f"width: 8px; height: 8px; background: {clr}; "
                                "border-radius: 50%"
                            )
                            ui.label(f"{ntype} ({cnt})").classes(
                                "text-xs"
                            ).style(f"color: {clr}")

                # Highcharts networkgraph — top 40 nodes, no edge data needed
                # for the force-layout to render nodes visually
                top_nodes = nodes[:40]
                hc_nodes = [
                    {
                        "id": n["label"][:35],
                        "color": _NODE_COLOR.get(n["node_type"], "#64748b"),
                        "marker": {
                            "radius": (
                                9
                                if n["node_type"] in ("orbit_goal", "concept")
                                else 5
                            )
                        },
                    }
                    for n in top_nodes
                ]

                # Minimal self-loop edges so Highcharts renders isolated nodes
                hc_data = [[n["id"], n["id"]] for n in hc_nodes]

                ui.chart(
                    {
                        "chart": {
                            "type": "networkgraph",
                            "backgroundColor": "#1a1a2e",
                            "height": 400,
                        },
                        "title": {"text": None},
                        "credits": {"enabled": False},
                        "plotOptions": {
                            "networkgraph": {
                                "layoutAlgorithm": {
                                    "enableSimulation": True,
                                    "friction": -0.9,
                                    "maxIterations": 1000,
                                },
                                "link": {
                                    "color": "transparent",
                                    "width": 0,
                                },
                                "dataLabels": {
                                    "enabled": True,
                                    "style": {
                                        "color": "#94a3b8",
                                        "fontSize": "9px",
                                        "fontWeight": "normal",
                                        "textOutline": "none",
                                    },
                                    "allowOverlap": False,
                                },
                            }
                        },
                        "series": [
                            {
                                "type": "networkgraph",
                                "data": hc_data,
                                "nodes": hc_nodes,
                            }
                        ],
                    }
                ).classes("w-full")

                # Recent node cards (bottom 12)
                with ui.column().classes("w-full gap-2 mt-4"):
                    ui.label("Recent nodes").classes(
                        "text-xs uppercase tracking-wide"
                    ).style("color: #64748b")
                    with ui.grid(columns=3).classes("w-full gap-2"):
                        for n in nodes[:12]:
                            clr = _NODE_COLOR.get(n["node_type"], "#94a3b8")
                            icon = _NODE_ICON.get(n["node_type"], "circle")
                            ts = (n.get("created_at") or "")[:10]
                            with ui.card().classes("p-3").style(
                                f"border-left: 3px solid {clr} !important"
                            ):
                                with ui.row().classes("items-start gap-2"):
                                    ui.icon(icon).classes("text-base mt-0.5").style(
                                        f"color: {clr}"
                                    )
                                    with ui.column().classes("flex-1 gap-0 min-w-0"):
                                        ui.label(
                                            n["label"][:45]
                                        ).classes(
                                            "text-xs font-semibold"
                                        ).style(
                                            "color: #e2e8f0; word-break: break-word"
                                        )
                                        ui.label(n["node_type"]).classes(
                                            "text-xs"
                                        ).style(f"color: {clr}")
                                        if ts:
                                            ui.label(ts).classes(
                                                "text-xs"
                                            ).style("color: #64748b")

            render_graph()

            # ── Thought Threads ────────────────────────────────────────────
            @ui.refreshable
            def render_threads() -> None:
                threads = cache["threads"]

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Thought Threads")
                    with ui.row().classes("gap-2 items-center"):
                        ui.label(f"{len(threads)} open").classes(
                            "text-sm"
                        ).style("color: #94a3b8")
                        ui.button(
                            "Maintenance",
                            icon="build",
                            on_click=lambda: asyncio.create_task(
                                _run_maintenance()
                            ),
                        ).props("flat no-caps dense").style(
                            "color: #64748b; font-size: 0.7rem"
                        )

                if not threads:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("check_circle").classes("text-4xl").style(
                            "color: #22c55e"
                        )
                        ui.label(
                            "No open thought threads — mind is clear!"
                        ).classes("text-sm mt-1").style("color: #94a3b8")
                    return

                with ui.column().classes("w-full gap-2"):
                    for t in threads:
                        status = t.get("status", "open")
                        rec = int(t.get("recurrence", 0))
                        clr = (
                            COLORS["primary"]
                            if status == "open"
                            else COLORS["text_muted"]
                        )
                        last = (t.get("last_seen_at") or "")[:10]

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full"):
                                ui.icon("thread").style(f"color: {clr}")
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(t["title"]).classes(
                                        "text-sm font-semibold"
                                    ).style("color: #e2e8f0")
                                    summary = (t.get("summary") or "").strip()
                                    if summary:
                                        ui.label(summary[:90]).classes(
                                            "text-xs"
                                        ).style("color: #94a3b8")
                                    if last:
                                        ui.label(
                                            f"Last seen {last}"
                                        ).classes("text-xs").style(
                                            "color: #64748b"
                                        )
                                with ui.column().classes("items-end gap-1"):
                                    ui.badge(status, color="grey").classes(
                                        "text-xs"
                                    )
                                    if rec > 0:
                                        ui.label(f"↩ {rec}×").classes(
                                            "text-xs"
                                        ).style("color: #f97316")

            render_threads()

            # ── Auto-refresh every 2 minutes ──────────────────────────────
            ui.timer(120.0, _on_refresh)
