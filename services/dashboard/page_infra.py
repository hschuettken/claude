"""Self-Optimizing Infrastructure dashboard page.

Talks to the self-optimizing-infra service at settings.self_optimizing_infra_url (port 8242).
Shows:
  - L0/L1/L2 monitor summary (services, nodes, decisions, proposals, chaos score)
  - Service health grid (L0) + node health grid (L1)
  - Decision engine — rules and pending decisions with approve/reject
  - Infra evolution proposals with approve/reject/implement
  - Chaos testing — recent runs, resilience report, trigger sweep
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
    "online": "#22c55e",
    "offline": "#ef4444",
    "unknown": "#64748b",
    "pending": "#eab308",
    "approved": "#22c55e",
    "rejected": "#ef4444",
    "executing": "#f97316",
    "done": "#22c55e",
    "failed": "#ef4444",
    "running": "#f97316",
    "passed": "#22c55e",
    "implemented": "#6366f1",
    "cancelled": "#64748b",
}

_RISK_COLOR: dict[str, str] = {
    "low": "#22c55e",
    "medium": "#f59e0b",
    "high": "#ef4444",
}

_SOURCE_ICON: dict[str, str] = {
    "proxmox": "computer",
    "k3s": "hub",
    "bootstrap": "dns",
    "L0": "monitor_heart",
    "L1": "storage",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /infra page."""

    base = settings.self_optimizing_infra_url

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
                if r.status_code in (200, 201, 202):
                    return r.json()
        except Exception:
            pass
        return None

    @ui.page("/infra")
    async def infra_page() -> None:
        create_page_layout("/infra")

        cache: dict[str, Any] = {
            "dashboard": None,
            "services": [],
            "nodes": [],
            "rules": [],
            "decisions": [],
            "proposals": [],
            "chaos_runs": [],
            "resilience": None,
        }

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get("/api/v1/dashboard"),
                _get("/api/v1/monitors/services"),
                _get("/api/v1/monitors/nodes"),
                _get("/api/v1/decisions/rules?enabled_only=false"),
                _get("/api/v1/decisions?limit=20"),
                _get("/api/v1/evolution/proposals?limit=20"),
                _get("/api/v1/chaos/runs?limit=10"),
                _get("/api/v1/chaos/resilience-report"),
            )
            cache["dashboard"] = results[0]
            cache["services"] = results[1] or []
            cache["nodes"] = results[2] or []
            cache["rules"] = results[3] or []
            cache["decisions"] = results[4] or []
            cache["proposals"] = results[5] or []
            cache["chaos_runs"] = results[6] or []
            cache["resilience"] = results[7]

        async def _on_refresh() -> None:
            await _load_data()
            render_summary.refresh()
            render_monitors.refresh()
            render_decisions.refresh()
            render_proposals.refresh()
            render_chaos.refresh()

        async def _approve_decision(decision_id: str) -> None:
            await _post(f"/api/v1/decisions/{decision_id}/approve", {"approved_by": "dashboard"})
            await _on_refresh()

        async def _reject_decision(decision_id: str) -> None:
            await _post(f"/api/v1/decisions/{decision_id}/reject", {"rejected_by": "dashboard", "reason": "Rejected via dashboard"})
            await _on_refresh()

        async def _approve_proposal(proposal_id: str) -> None:
            await _post(f"/api/v1/evolution/proposals/{proposal_id}/approve", {"resolved_by": "dashboard", "reason": "Approved via dashboard"})
            await _on_refresh()

        async def _reject_proposal(proposal_id: str) -> None:
            await _post(f"/api/v1/evolution/proposals/{proposal_id}/reject", {"resolved_by": "dashboard", "reason": "Rejected via dashboard"})
            await _on_refresh()

        async def _implement_proposal(proposal_id: str) -> None:
            await _post(f"/api/v1/evolution/proposals/{proposal_id}/implement", {"resolved_by": "dashboard"})
            await _on_refresh()

        async def _trigger_evaluation() -> None:
            await _post("/api/v1/decisions/evaluate")
            ui.notify("Evaluation triggered", type="positive")

        async def _trigger_poll() -> None:
            await _post("/api/v1/monitors/poll")
            ui.notify("L1 poll triggered", type="positive")

        async def _trigger_chaos_sweep() -> None:
            await _post("/api/v1/chaos/sweep")
            ui.notify("Chaos sweep triggered", type="warning")

        async def _trigger_evolution_analysis() -> None:
            await _post("/api/v1/evolution/analyze")
            ui.notify("Evolution analysis triggered", type="positive")

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # ── Header ─────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Self-Optimizing Infrastructure")
                    ui.label(
                        "L0/L1/L2 Monitors · Decision Engine · Evolution · Chaos"
                    ).style("color: #94a3b8")
                with ui.row().classes("gap-2"):
                    ui.button(
                        "Poll L1",
                        icon="radar",
                        on_click=lambda: asyncio.create_task(_trigger_poll()),
                    ).props("flat no-caps dense").style("color: #94a3b8; font-size: 0.75rem")
                    ui.button(
                        "Evaluate",
                        icon="rule",
                        on_click=lambda: asyncio.create_task(_trigger_evaluation()),
                    ).props("flat no-caps dense").style("color: #94a3b8; font-size: 0.75rem")
                    ui.button(
                        "Refresh",
                        icon="refresh",
                        on_click=_on_refresh,
                    ).props("flat no-caps").style("color: #94a3b8")

            # ── Summary metrics ────────────────────────────────────────────
            @ui.refreshable
            def render_summary() -> None:
                d = cache["dashboard"] or {}
                svc_on = d.get("services_online", 0)
                svc_off = d.get("services_offline", 0)
                nodes_on = d.get("nodes_online", 0)
                nodes_off = d.get("nodes_offline", 0)
                open_dec = d.get("open_decisions", 0)
                auto_today = d.get("auto_approved_today", 0)
                open_prop = d.get("open_proposals", 0)
                score = d.get("chaos_resilience_score")
                score_str = f"{score:.0%}" if score is not None else "—"
                engine_active = d.get("decision_engine_active", False)

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for icon_name, label, val, clr in [
                        ("monitor_heart", "Services Online", svc_on, COLORS["online"]),
                        ("wifi_off", "Services Offline", svc_off, COLORS["offline"] if svc_off > 0 else COLORS["text_dim"]),
                        ("storage", "Nodes Online", nodes_on, COLORS["battery"]),
                        ("cloud_off", "Nodes Offline", nodes_off, COLORS["offline"] if nodes_off > 0 else COLORS["text_dim"]),
                        ("rule", "Open Decisions", open_dec, COLORS["warning"] if open_dec > 0 else COLORS["text_dim"]),
                        ("auto_fix_high", "Auto-Approved Today", auto_today, COLORS["primary"]),
                        ("lightbulb", "Open Proposals", open_prop, COLORS["ev"] if open_prop > 0 else COLORS["text_dim"]),
                        ("science", "Resilience Score", score_str, COLORS["grid_export"] if score and score >= 0.8 else COLORS["warning"]),
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
                    if engine_active is not None:
                        with ui.card().classes("p-4 flex-1 min-w-[130px]").style(
                            f"border-left: 4px solid {'#22c55e' if engine_active else '#ef4444'} !important"
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("psychology_alt").style(f"color: {'#22c55e' if engine_active else '#ef4444'}")
                                ui.label("Decision Engine").classes("text-xs uppercase tracking-wide").style("color: #94a3b8")
                            ui.label("Active" if engine_active else "Off").classes("text-3xl font-bold mt-1").style(
                                f"color: {'#22c55e' if engine_active else '#ef4444'}"
                            )

            render_summary()

            # ── L0/L1 Monitor grids ────────────────────────────────────────
            @ui.refreshable
            def render_monitors() -> None:
                services = cache["services"]
                nodes = cache["nodes"]

                with ui.row().classes("w-full gap-6"):
                    # L0 — Services
                    with ui.column().classes("flex-1 gap-3 min-w-[300px]"):
                        with ui.row().classes("items-center justify-between"):
                            section_title("L0 — Service Agents")
                            ui.label(f"{len(services)} tracked").classes("text-sm").style("color: #94a3b8")

                        if not services:
                            with ui.card().classes("w-full p-6 text-center"):
                                ui.icon("monitor_heart").classes("text-4xl").style("color: #64748b")
                                ui.label("No heartbeats received yet").classes("text-sm mt-1").style("color: #94a3b8")
                        else:
                            with ui.column().classes("w-full gap-2"):
                                for svc in services:
                                    status = svc.get("status", "unknown")
                                    clr = _STATUS_COLOR.get(status, "#64748b")
                                    last_seen = (svc.get("last_seen_at") or "")[:16].replace("T", " ")
                                    meta = svc.get("metadata") or {}
                                    uptime = meta.get("uptime_seconds")
                                    mem = meta.get("memory_mb")

                                    with ui.card().classes("w-full p-3").style(
                                        f"border-left: 3px solid {clr} !important"
                                    ):
                                        with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                            ui.icon("circle").classes("text-xs").style(f"color: {clr}")
                                            with ui.column().classes("flex-1 gap-0 min-w-0"):
                                                ui.label(svc.get("service_name", "—")).classes(
                                                    "text-sm font-semibold"
                                                ).style("color: #e2e8f0")
                                                with ui.row().classes("gap-3"):
                                                    ui.label(status).classes("text-xs").style(f"color: {clr}")
                                                    if last_seen:
                                                        ui.label(f"seen {last_seen}").classes("text-xs").style("color: #64748b")
                                                    if uptime is not None:
                                                        ui.label(f"up {int(uptime // 3600)}h").classes("text-xs").style("color: #64748b")
                                                    if mem is not None:
                                                        ui.label(f"{mem:.0f} MB").classes("text-xs").style("color: #64748b")

                    # L1 — Nodes
                    with ui.column().classes("flex-1 gap-3 min-w-[300px]"):
                        with ui.row().classes("items-center justify-between"):
                            section_title("L1 — Infra Nodes")
                            ui.label(f"{len(nodes)} tracked").classes("text-sm").style("color: #94a3b8")

                        if not nodes:
                            with ui.card().classes("w-full p-6 text-center"):
                                ui.icon("storage").classes("text-4xl").style("color: #64748b")
                                ui.label("No infra nodes polled yet").classes("text-sm mt-1").style("color: #94a3b8")
                        else:
                            with ui.column().classes("w-full gap-2"):
                                for node in nodes:
                                    status = node.get("status", "unknown")
                                    clr = _STATUS_COLOR.get(status, "#64748b")
                                    source = node.get("source", "")
                                    src_icon = _SOURCE_ICON.get(source, "dns")
                                    cpu = node.get("cpu_percent")
                                    mem = node.get("mem_percent")
                                    disk = node.get("disk_percent")

                                    with ui.card().classes("w-full p-3").style(
                                        f"border-left: 3px solid {clr} !important"
                                    ):
                                        with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                            ui.icon(src_icon).classes("text-sm").style(f"color: {clr}")
                                            with ui.column().classes("flex-1 gap-0 min-w-0"):
                                                with ui.row().classes("items-center gap-2"):
                                                    ui.label(node.get("node_name", "—")).classes(
                                                        "text-sm font-semibold"
                                                    ).style("color: #e2e8f0")
                                                    ui.badge(source).props("outline").classes("text-xs").style(
                                                        f"color: {COLORS['text_muted']}; border-color: {COLORS['border']}"
                                                    )
                                                with ui.row().classes("gap-3 flex-wrap"):
                                                    if cpu is not None:
                                                        cpu_clr = COLORS["grid_import"] if cpu > 85 else COLORS["warning"] if cpu > 70 else COLORS["text_dim"]
                                                        ui.label(f"CPU {cpu:.0f}%").classes("text-xs").style(f"color: {cpu_clr}")
                                                    if mem is not None:
                                                        mem_clr = COLORS["grid_import"] if mem > 90 else COLORS["warning"] if mem > 75 else COLORS["text_dim"]
                                                        ui.label(f"Mem {mem:.0f}%").classes("text-xs").style(f"color: {mem_clr}")
                                                    if disk is not None:
                                                        disk_clr = COLORS["grid_import"] if disk > 90 else COLORS["warning"] if disk > 75 else COLORS["text_dim"]
                                                        ui.label(f"Disk {disk:.0f}%").classes("text-xs").style(f"color: {disk_clr}")

            render_monitors()

            # ── Decision Engine ─────────────────────────────────────────────
            @ui.refreshable
            def render_decisions() -> None:
                rules = cache["rules"]
                decisions = cache["decisions"]

                pending = [d for d in decisions if d.get("status") in ("pending",)]
                recent = [d for d in decisions if d.get("status") not in ("pending",)][:10]

                # Rules summary
                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Decision Engine")
                    with ui.row().classes("gap-2 items-center"):
                        enabled_count = sum(1 for r in rules if r.get("enabled"))
                        ui.label(f"{enabled_count}/{len(rules)} rules enabled").classes("text-sm").style("color: #94a3b8")
                        ui.button(
                            "Evaluate Now",
                            icon="play_arrow",
                            on_click=lambda: asyncio.create_task(_trigger_evaluation()),
                        ).props("flat no-caps dense").style("color: #6366f1; font-size: 0.75rem")

                # Active rules
                if rules:
                    with ui.expansion("Decision Rules", icon="rule").classes("w-full").props("dense"):
                        with ui.column().classes("w-full gap-2 p-2"):
                            for rule in rules:
                                enabled = rule.get("enabled", False)
                                risk = rule.get("risk_level", "low")
                                risk_clr = _RISK_COLOR.get(risk, "#64748b")
                                auto = rule.get("auto_approve", False)
                                clr = COLORS["online"] if enabled else COLORS["text_dim"]

                                with ui.card().classes("w-full p-3").style(
                                    f"border-left: 3px solid {clr} !important"
                                ):
                                    with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                        with ui.column().classes("flex-1 gap-0"):
                                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                                ui.label(rule.get("name", "—")).classes(
                                                    "text-sm font-semibold"
                                                ).style("color: #e2e8f0")
                                                ui.badge(risk).classes("text-xs").style(
                                                    f"background: {risk_clr}20; color: {risk_clr}"
                                                )
                                                if auto:
                                                    ui.badge("auto-approve").props("outline").classes("text-xs").style(
                                                        "color: #6366f1; border-color: #6366f1"
                                                    )
                                                if not enabled:
                                                    ui.badge("disabled").classes("text-xs").style("color: #64748b")
                                            desc = (rule.get("description") or "").strip()
                                            if desc:
                                                ui.label(desc[:100]).classes("text-xs").style("color: #94a3b8")
                                            with ui.row().classes("gap-3"):
                                                ui.label(f"condition: {rule.get('condition_type', '?')}").classes("text-xs").style("color: #64748b")
                                                ui.label(f"action: {rule.get('action_type', '?')}").classes("text-xs").style("color: #64748b")
                                                ui.label(f"cooldown: {rule.get('cooldown_minutes', 0)}m").classes("text-xs").style("color: #64748b")

                # Pending decisions requiring approval
                if pending:
                    with ui.card().classes("w-full p-4").style("border: 1px solid #f59e0b !important"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("pending_actions").style("color: #f59e0b")
                            ui.label(f"{len(pending)} Pending Approval").classes("text-base font-bold").style("color: #f59e0b")
                        with ui.column().classes("w-full gap-2"):
                            for d in pending:
                                did = str(d.get("id", ""))
                                risk = d.get("risk_level", "low")
                                risk_clr = _RISK_COLOR.get(risk, "#64748b")
                                trigger = d.get("trigger_data") or {}

                                with ui.card().classes("w-full p-3").style(
                                    f"border-left: 3px solid {risk_clr} !important"
                                ):
                                    with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                        with ui.column().classes("flex-1 gap-0"):
                                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                                ui.label(d.get("rule_name", "—")).classes("text-sm font-semibold").style("color: #e2e8f0")
                                                ui.badge(risk).classes("text-xs").style(
                                                    f"background: {risk_clr}20; color: {risk_clr}"
                                                )
                                                ui.badge(d.get("action_type", "—")).props("outline").classes("text-xs").style("color: #94a3b8")
                                            if trigger:
                                                target = trigger.get("service") or trigger.get("node") or str(trigger)[:60]
                                                ui.label(f"Target: {target}").classes("text-xs").style("color: #94a3b8")
                                            created = (d.get("created_at") or "")[:16].replace("T", " ")
                                            if created:
                                                ui.label(created).classes("text-xs").style("color: #64748b")
                                        with ui.row().classes("gap-2"):
                                            ui.button(
                                                "Approve",
                                                icon="check",
                                                on_click=lambda i=did: asyncio.create_task(_approve_decision(i)),
                                            ).props("flat no-caps dense").style("color: #22c55e; font-size: 0.75rem")
                                            ui.button(
                                                "Reject",
                                                icon="close",
                                                on_click=lambda i=did: asyncio.create_task(_reject_decision(i)),
                                            ).props("flat no-caps dense").style("color: #ef4444; font-size: 0.75rem")

                # Recent decision history
                with ui.row().classes("w-full items-center justify-between mt-2"):
                    ui.label("Recent Decisions").classes("text-base font-semibold").style("color: #e2e8f0")
                    ui.label(f"{len(recent)} shown").classes("text-sm").style("color: #94a3b8")

                if not recent:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("check_circle").classes("text-3xl").style("color: #22c55e")
                        ui.label("No decisions executed yet").classes("text-sm mt-1").style("color: #94a3b8")
                else:
                    with ui.column().classes("w-full gap-2"):
                        for d in recent:
                            status = d.get("status", "done")
                            clr = _STATUS_COLOR.get(status, "#64748b")
                            risk = d.get("risk_level", "low")
                            risk_clr = _RISK_COLOR.get(risk, "#64748b")
                            auto = d.get("auto_approved", False)
                            created = (d.get("created_at") or "")[:16].replace("T", " ")

                            with ui.card().classes("w-full p-3").style(
                                f"border-left: 3px solid {clr} !important"
                            ):
                                with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                    with ui.column().classes("flex-1 gap-0"):
                                        with ui.row().classes("items-center gap-2 flex-wrap"):
                                            ui.label(d.get("rule_name", "—")).classes("text-sm font-semibold").style("color: #e2e8f0")
                                            ui.badge(status).classes("text-xs").style(f"background: {clr}20; color: {clr}")
                                            ui.badge(risk).props("outline").classes("text-xs").style(f"color: {risk_clr}")
                                            if auto:
                                                ui.badge("auto").props("outline").classes("text-xs").style("color: #6366f1; border-color: #6366f1")
                                        with ui.row().classes("gap-3"):
                                            ui.label(d.get("action_type", "—")).classes("text-xs").style("color: #94a3b8")
                                            if created:
                                                ui.label(created).classes("text-xs").style("color: #64748b")
                                            result = d.get("result")
                                            if result and isinstance(result, str):
                                                ui.label(result[:80]).classes("text-xs").style("color: #64748b")

            render_decisions()

            # ── Evolution Proposals ─────────────────────────────────────────
            @ui.refreshable
            def render_proposals() -> None:
                proposals = cache["proposals"]
                pending = [p for p in proposals if p.get("status") == "pending"]
                others = [p for p in proposals if p.get("status") != "pending"][:8]

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Infra Evolution Proposals")
                    with ui.row().classes("gap-2 items-center"):
                        if pending:
                            ui.label(f"{len(pending)} pending").classes("text-sm").style("color: #eab308")
                        ui.button(
                            "Analyze",
                            icon="analytics",
                            on_click=lambda: asyncio.create_task(_trigger_evolution_analysis()),
                        ).props("flat no-caps dense").style("color: #a855f7; font-size: 0.75rem")

                if not proposals:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("lightbulb").classes("text-5xl").style("color: #64748b")
                        ui.label("No proposals yet — trigger an analysis run").classes("mt-2 text-sm").style("color: #94a3b8")
                    return

                _PROPOSAL_ICON: dict[str, str] = {
                    "scale_cpu": "speed",
                    "scale_memory": "memory",
                    "expand_storage": "storage",
                    "improve_reliability": "health_and_safety",
                    "decommission_node": "delete",
                    "rebalance_workload": "balance",
                    "add_node": "add_circle",
                    "remove_node": "remove_circle",
                    "upgrade_version": "upgrade",
                }

                with ui.column().classes("w-full gap-2"):
                    for p in pending + others:
                        pid = str(p.get("id", ""))
                        status = p.get("status", "pending")
                        clr = _STATUS_COLOR.get(status, "#64748b")
                        ptype = p.get("proposal_type", "")
                        p_icon = _PROPOSAL_ICON.get(ptype, "lightbulb")
                        impact = p.get("estimated_impact") or {}
                        headroom = impact.get("headroom_gain_pct")
                        created = (p.get("created_at") or "")[:16].replace("T", " ")

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                ui.icon(p_icon).classes("text-xl").style(f"color: {clr}")
                                with ui.column().classes("flex-1 gap-0"):
                                    with ui.row().classes("items-center gap-2 flex-wrap"):
                                        ui.label(p.get("title", "—")).classes(
                                            "text-sm font-semibold"
                                        ).style("color: #e2e8f0")
                                        ui.badge(status).classes("text-xs").style(
                                            f"background: {clr}20; color: {clr}"
                                        )
                                        ui.badge(ptype).props("outline").classes("text-xs").style("color: #94a3b8")
                                    desc = (p.get("description") or "").strip()
                                    if desc:
                                        ui.label(desc[:120]).classes("text-xs").style("color: #94a3b8")
                                    with ui.row().classes("gap-3"):
                                        if p.get("resource_target"):
                                            ui.label(f"target: {p['resource_target']}").classes("text-xs").style("color: #64748b")
                                        if headroom is not None:
                                            ui.label(f"+{headroom:.0f}% headroom").classes("text-xs").style("color: #22c55e")
                                        if created:
                                            ui.label(created).classes("text-xs").style("color: #64748b")

                                if status == "pending":
                                    with ui.row().classes("gap-2"):
                                        ui.button(
                                            "Approve",
                                            icon="check",
                                            on_click=lambda i=pid: asyncio.create_task(_approve_proposal(i)),
                                        ).props("flat no-caps dense").style("color: #22c55e; font-size: 0.75rem")
                                        ui.button(
                                            "Reject",
                                            icon="close",
                                            on_click=lambda i=pid: asyncio.create_task(_reject_proposal(i)),
                                        ).props("flat no-caps dense").style("color: #ef4444; font-size: 0.75rem")
                                elif status == "approved":
                                    ui.button(
                                        "Implement",
                                        icon="rocket_launch",
                                        on_click=lambda i=pid: asyncio.create_task(_implement_proposal(i)),
                                    ).props("flat no-caps dense").style("color: #6366f1; font-size: 0.75rem")

            render_proposals()

            # ── Chaos Testing ───────────────────────────────────────────────
            @ui.refreshable
            def render_chaos() -> None:
                runs = cache["chaos_runs"]
                report = cache["resilience"] or {}

                total = report.get("total_experiments", 0)
                passed = report.get("passed", 0)
                failed = report.get("failed", 0)
                score = report.get("resilience_score")
                avg_recovery = report.get("avg_recovery_time_seconds")
                score_str = f"{score:.0%}" if score is not None else "—"
                score_clr = (
                    COLORS["online"] if score is not None and score >= 0.8
                    else COLORS["warning"] if score is not None and score >= 0.5
                    else COLORS["offline"] if score is not None
                    else COLORS["text_dim"]
                )

                with ui.row().classes("w-full items-center justify-between"):
                    section_title("Chaos Testing")
                    ui.button(
                        "Run Sweep",
                        icon="science",
                        on_click=lambda: asyncio.create_task(_trigger_chaos_sweep()),
                    ).props("flat no-caps dense").style("color: #f59e0b; font-size: 0.75rem")

                # Resilience summary
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    for icon_name, label, val, clr in [
                        ("science", "Total Experiments", total, COLORS["primary"]),
                        ("check_circle", "Passed", passed, COLORS["online"]),
                        ("cancel", "Failed", failed, COLORS["offline"] if failed > 0 else COLORS["text_dim"]),
                        ("shield", "Resilience Score", score_str, score_clr),
                        ("timer", "Avg Recovery", f"{avg_recovery:.0f}s" if avg_recovery else "—", COLORS["battery"]),
                    ]:
                        with ui.card().classes("p-4 flex-1 min-w-[120px]").style(
                            f"border-left: 4px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon(icon_name).style(f"color: {clr}")
                                ui.label(label).classes("text-xs uppercase tracking-wide").style("color: #94a3b8")
                            ui.label(str(val)).classes("text-3xl font-bold mt-1").style(f"color: {clr}")

                # Recent chaos runs
                with ui.row().classes("w-full items-center justify-between mt-2"):
                    ui.label("Recent Runs").classes("text-base font-semibold").style("color: #e2e8f0")
                    ui.label(f"{len(runs)} shown").classes("text-sm").style("color: #94a3b8")

                if not runs:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("science").classes("text-4xl").style("color: #64748b")
                        ui.label(
                            "No chaos experiments run yet"
                        ).classes("text-sm mt-1").style("color: #94a3b8")
                        ui.label(
                            "Chaos runs in simulation mode unless SOI_CHAOS_ENABLED=true"
                        ).classes("text-xs mt-1").style("color: #64748b")
                    return

                _CHAOS_TYPE_ICON = {
                    "service_kill": "stop_circle",
                    "latency_injection": "slow_motion_video",
                    "node_failure": "cloud_off",
                }

                with ui.column().classes("w-full gap-2"):
                    for run in runs:
                        status = run.get("status", "passed")
                        clr = _STATUS_COLOR.get(status, "#64748b")
                        etype = run.get("experiment_type", "")
                        e_icon = _CHAOS_TYPE_ICON.get(etype, "science")
                        target = run.get("target", "—")
                        recovery = run.get("recovery_time_seconds")
                        started = (run.get("started_at") or "")[:16].replace("T", " ")

                        with ui.card().classes("w-full p-3").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                                ui.icon(e_icon).classes("text-sm").style(f"color: {clr}")
                                with ui.column().classes("flex-1 gap-0"):
                                    with ui.row().classes("items-center gap-2 flex-wrap"):
                                        ui.label(f"{etype}:{target}").classes("text-sm font-semibold").style("color: #e2e8f0")
                                        ui.badge(status).classes("text-xs").style(
                                            f"background: {clr}20; color: {clr}"
                                        )
                                    with ui.row().classes("gap-3"):
                                        if started:
                                            ui.label(started).classes("text-xs").style("color: #64748b")
                                        if recovery is not None:
                                            ui.label(f"recovery: {recovery}s").classes("text-xs").style("color: #94a3b8")

            render_chaos()

            # ── Auto-refresh every 30 seconds ──────────────────────────────
            ui.timer(30.0, _on_refresh)
