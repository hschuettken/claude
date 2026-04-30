"""Agent Economy dashboard page — registry, tasks, budget, spawn requests.

Talks to the agent-economy service at settings.agent_economy_url (port 8240).
Shows:
  - Fleet stats (active agents, tasks today, tokens used)
  - Agent registry table with reputation scores and budget
  - Recent task list with status badges
  - Pending spawn requests with approve/reject actions
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


_STATUS_COLOR: dict[str, str] = {
    "active": "#22c55e",
    "busy": "#f97316",
    "inactive": "#64748b",
    "created": "#6366f1",
    "claimed": "#f97316",
    "completed": "#22c55e",
    "failed": "#ef4444",
    "pending": "#eab308",
    "approved": "#22c55e",
    "rejected": "#ef4444",
    "cancelled": "#64748b",
}

_AGENT_TYPE_ICON: dict[str, str] = {
    "main": "hub",
    "architect": "architecture",
    "dev": "code",
    "qa": "bug_report",
    "devops": "settings",
    "team-lead": "supervisor_account",
    "backlog-agent": "format_list_bulleted",
    "spec-retro": "history",
    "custom": "smart_toy",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /agent-economy page."""

    base = settings.agent_economy_url

    async def _get(path: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}{path}")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    async def _post(path: str, json: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}{path}", json=json or {})
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        return None

    @ui.page("/agent-economy")
    async def agent_economy_page() -> None:
        create_page_layout("/agent-economy")

        cache: dict[str, Any] = {
            "stats": None,
            "agents": [],
            "tasks": [],
            "spawn": [],
        }

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get("/api/v1/dashboard"),
                _get("/api/v1/agents"),
                _get("/api/v1/tasks?limit=20"),
                _get("/api/v1/spawn/requests?status=pending"),
            )
            cache["stats"] = results[0]
            cache["agents"] = results[1] or []
            cache["tasks"] = results[2] or []
            cache["spawn"] = results[3] or []

        async def _on_refresh() -> None:
            await _load_data()
            render_stats.refresh()
            render_agents.refresh()
            render_tasks.refresh()
            render_spawn.refresh()

        async def _approve_spawn(request_id: str) -> None:
            await _post(f"/api/v1/spawn/requests/{request_id}/approve", {"approved_by": "dashboard"})
            await _on_refresh()

        async def _reject_spawn(request_id: str) -> None:
            await _post(f"/api/v1/spawn/requests/{request_id}/reject", {"reason": "Rejected via dashboard"})
            await _on_refresh()

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # ── Header ─────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Agent Economy")
                    ui.label(
                        "Registry · Tasks · Budget · Spawn Requests"
                    ).style("color: #94a3b8")
                ui.button(
                    "Refresh",
                    icon="refresh",
                    on_click=_on_refresh,
                ).props("flat no-caps").style("color: #94a3b8")

            # ── Fleet stats ────────────────────────────────────────────────
            @ui.refreshable
            def render_stats() -> None:
                s = cache["stats"] or {}
                total = s.get("total_agents", 0)
                active = s.get("active_agents", 0)
                busy = s.get("busy_agents", 0)
                created = s.get("tasks_created_today", 0)
                completed = s.get("tasks_completed_today", 0)
                failed = s.get("tasks_failed_today", 0)
                tokens = s.get("total_tokens_used", 0)

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for icon_name, label, val, clr in [
                        ("smart_toy", "Total Agents", total, COLORS["primary"]),
                        ("check_circle", "Active", active, COLORS["grid_export"]),
                        ("hourglass_top", "Busy", busy, COLORS["house"]),
                        ("add_task", "Tasks Today", created, COLORS["battery"]),
                        ("task_alt", "Completed", completed, COLORS["grid_export"]),
                        ("cancel", "Failed", failed, COLORS["grid_import"]),
                        ("token", "Tokens Used", tokens, COLORS["ev"]),
                    ]:
                        with ui.card().classes("p-4 flex-1 min-w-[130px]").style(
                            f"border-left: 4px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon(icon_name).style(f"color: {clr}")
                                ui.label(label).classes("text-xs uppercase tracking-wide").style(
                                    "color: #94a3b8"
                                )
                            ui.label(str(val)).classes("text-3xl font-bold mt-1").style(
                                f"color: {clr}"
                            )

            render_stats()

            # ── Agent registry ─────────────────────────────────────────────
            @ui.refreshable
            def render_agents() -> None:
                agents = cache["agents"]

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Agent Registry")
                    ui.label(f"{len(agents)} agents").classes("text-sm").style(
                        "color: #94a3b8"
                    )

                if not agents:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("smart_toy").classes("text-5xl").style("color: #64748b")
                        ui.label(
                            "No agents registered yet"
                        ).classes("mt-2 text-sm").style("color: #94a3b8")
                    return

                with ui.column().classes("w-full gap-2"):
                    for ag in agents:
                        status = ag.get("status", "inactive")
                        atype = ag.get("agent_type", "custom")
                        icon = _AGENT_TYPE_ICON.get(atype, "smart_toy")
                        clr = _STATUS_COLOR.get(status, "#64748b")
                        rep = float(ag.get("reputation_score", 0.0))
                        tasks_done = ag.get("tasks_completed", 0)
                        tasks_fail = ag.get("tasks_failed", 0)
                        budget_used = ag.get("budget_tokens_used", 0)
                        budget_limit = ag.get("budget_tokens_limit", 0)
                        caps = ag.get("capabilities") or []

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                ui.icon(icon).classes("text-xl").style(f"color: {clr}")
                                with ui.column().classes("flex-1 gap-0 min-w-0"):
                                    with ui.row().classes("items-center gap-2 flex-wrap"):
                                        ui.label(ag.get("agent_name", "—")).classes(
                                            "text-sm font-semibold"
                                        ).style("color: #e2e8f0")
                                        ui.badge(atype).props("outline").classes("text-xs").style(
                                            f"color: {clr}; border-color: {clr}"
                                        )
                                        ui.badge(status).classes("text-xs").style(
                                            f"background: {clr}20; color: {clr}"
                                        )
                                    desc = (ag.get("description") or "").strip()
                                    if desc:
                                        ui.label(desc[:80]).classes("text-xs").style(
                                            "color: #94a3b8"
                                        )
                                    if caps:
                                        ui.label(", ".join(caps[:5])).classes("text-xs").style(
                                            "color: #64748b"
                                        )

                                with ui.grid(columns=4).classes("gap-4"):
                                    for lbl, val, unit in [
                                        ("Reputation", f"{rep:.2f}", "/ 1.0"),
                                        ("Done", str(tasks_done), "tasks"),
                                        ("Failed", str(tasks_fail), "tasks"),
                                        (
                                            "Budget",
                                            str(budget_used),
                                            f"/ {budget_limit}" if budget_limit else "∞",
                                        ),
                                    ]:
                                        with ui.column().classes("items-center gap-0"):
                                            tok_clr = (
                                                COLORS["grid_import"]
                                                if lbl == "Failed" and tasks_fail > 0
                                                else COLORS["text_muted"]
                                            )
                                            if lbl == "Reputation":
                                                tok_clr = (
                                                    COLORS["grid_export"] if rep >= 0.8
                                                    else COLORS["warning"] if rep >= 0.5
                                                    else COLORS["grid_import"]
                                                )
                                            ui.label(val).classes("text-lg font-bold").style(
                                                f"color: {tok_clr}"
                                            )
                                            ui.label(lbl).classes("text-xs").style(
                                                "color: #64748b"
                                            )
                                            ui.label(unit).classes("text-xs").style(
                                                "color: #64748b"
                                            )

            render_agents()

            # ── Recent tasks ───────────────────────────────────────────────
            @ui.refreshable
            def render_tasks() -> None:
                tasks = cache["tasks"]

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Recent Tasks")
                    ui.label(f"{len(tasks)} shown").classes("text-sm").style(
                        "color: #94a3b8"
                    )

                if not tasks:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("assignment").classes("text-4xl").style("color: #64748b")
                        ui.label("No tasks yet").classes("text-sm mt-1").style(
                            "color: #94a3b8"
                        )
                    return

                with ui.column().classes("w-full gap-2"):
                    for t in tasks:
                        status = t.get("status", "created")
                        clr = _STATUS_COLOR.get(status, "#64748b")
                        priority = t.get("priority", 5)
                        tokens = t.get("tokens_used", 0)
                        assigned = t.get("assigned_to") or "—"
                        created = (t.get("created_at") or "")[:16].replace("T", " ")

                        with ui.card().classes("w-full p-3").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                with ui.column().classes("flex-1 gap-0 min-w-0"):
                                    with ui.row().classes("items-center gap-2 flex-wrap"):
                                        ui.label(t.get("title", "—")).classes(
                                            "text-sm font-semibold"
                                        ).style("color: #e2e8f0")
                                        ui.badge(status).classes("text-xs").style(
                                            f"background: {clr}20; color: {clr}"
                                        )
                                        ui.badge(f"P{priority}").props("outline").classes(
                                            "text-xs"
                                        ).style("color: #94a3b8")
                                    with ui.row().classes("gap-3"):
                                        ui.label(f"type: {t.get('task_type', '?')}").classes(
                                            "text-xs"
                                        ).style("color: #64748b")
                                        ui.label(f"agent: {assigned[:20]}").classes(
                                            "text-xs"
                                        ).style("color: #64748b")
                                        if tokens:
                                            ui.label(f"{tokens:,} tok").classes(
                                                "text-xs"
                                            ).style("color: #64748b")
                                        if created:
                                            ui.label(created).classes("text-xs").style(
                                                "color: #64748b"
                                            )

            render_tasks()

            # ── Spawn requests ─────────────────────────────────────────────
            @ui.refreshable
            def render_spawn() -> None:
                requests = cache["spawn"]

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Pending Spawn Requests")
                    if requests:
                        ui.label(f"{len(requests)} pending").classes("text-sm").style(
                            "color: #eab308"
                        )

                if not requests:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("check_circle").classes("text-3xl").style(
                            "color: #22c55e"
                        )
                        ui.label("No pending spawn requests").classes("text-sm mt-1").style(
                            "color: #94a3b8"
                        )
                    return

                with ui.column().classes("w-full gap-2"):
                    for req in requests:
                        rid = req.get("request_id", "")
                        requester = req.get("requested_by", "—")
                        purpose = req.get("purpose", "")
                        caps = req.get("requested_capabilities") or []
                        created = (req.get("created_at") or "")[:16].replace("T", " ")

                        with ui.card().classes("w-full p-4").style(
                            "border-left: 3px solid #eab308 !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                ui.icon("add_circle").style("color: #eab308")
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(
                                        f"Spawn request from {requester}"
                                    ).classes("text-sm font-semibold").style("color: #e2e8f0")
                                    if purpose:
                                        ui.label(purpose[:100]).classes("text-xs").style(
                                            "color: #94a3b8"
                                        )
                                    if caps:
                                        ui.label(
                                            f"Capabilities: {', '.join(caps)}"
                                        ).classes("text-xs").style("color: #64748b")
                                    if created:
                                        ui.label(created).classes("text-xs").style(
                                            "color: #64748b"
                                        )
                                with ui.row().classes("gap-2"):
                                    ui.button(
                                        "Approve",
                                        icon="check",
                                        on_click=lambda r=rid: asyncio.create_task(
                                            _approve_spawn(r)
                                        ),
                                    ).props("flat no-caps dense").style(
                                        "color: #22c55e; font-size: 0.75rem"
                                    )
                                    ui.button(
                                        "Reject",
                                        icon="close",
                                        on_click=lambda r=rid: asyncio.create_task(
                                            _reject_spawn(r)
                                        ),
                                    ).props("flat no-caps dense").style(
                                        "color: #ef4444; font-size: 0.75rem"
                                    )

            render_spawn()

            # ── Auto-refresh every 30 seconds ──────────────────────────────
            ui.timer(30.0, _on_refresh)
