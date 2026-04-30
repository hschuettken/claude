"""HenningGPT Personal AI Model dashboard page — FR #42.

Displays all four phases of the HenningGPT system:
  Phase 1 — Decision memory RAG (recent decisions + search)
  Phase 2 — Preference graph with WHY edges (grouped by context)
  Phase 3 — Active learning accuracy report + pending predictions
  Phase 4 — Delegation mode sandbox (confidence scoring)

Talks to the orchestrator API at settings.orchestrator_url (port 8100).
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


_CTX_COLOR: dict[str, str] = {
    "energy": COLORS["solar"],
    "family": COLORS["ev"],
    "work": COLORS["primary"],
    "health": COLORS["grid_export"],
    "general": COLORS["text_muted"],
}

_CTX_ICON: dict[str, str] = {
    "energy": "bolt",
    "family": "family_restroom",
    "work": "code",
    "health": "fitness_center",
    "general": "help_outline",
}


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /henning-gpt page."""

    base = settings.orchestrator_url
    api_key = settings.orchestrator_api_key

    def _headers() -> dict[str, str]:
        return {"X-API-Key": api_key} if api_key else {}

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(path: str, params: dict | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    f"{base}{path}", params=params or {}, headers=_headers()
                )
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    async def _post(path: str, body: dict | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{base}{path}", json=body or {}, headers=_headers()
                )
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    # ── Page ──────────────────────────────────────────────────────────────────

    @ui.page("/henning-gpt")
    async def henning_gpt_page() -> None:
        create_page_layout("/henning-gpt")

        cache: dict[str, Any] = {
            "decisions": [],
            "preferences": [],
            "accuracy": None,
            "pending": [],
            "policy_energy": None,
        }

        # Search inputs (mutable containers)
        search_state: dict[str, str] = {"query": "", "user_id": "henning"}

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get(
                    "/companion/henninggpt/decisions/recent",
                    {"user_id": "henning", "limit": 6},
                ),
                _get("/companion/henninggpt/preferences", {"user_id": "henning"}),
                _get(
                    "/companion/henninggpt/accuracy",
                    {"user_id": "henning", "days": 30},
                ),
                _get(
                    "/companion/henninggpt/predictions/pending",
                    {"user_id": "henning", "limit": 5},
                ),
                _get("/companion/henninggpt/delegate/policy/energy"),
            )
            cache["decisions"] = (results[0] or {}).get("decisions", [])
            cache["preferences"] = (results[1] or {}).get("preferences", [])
            cache["accuracy"] = results[2]
            cache["pending"] = (results[3] or {}).get("predictions", [])
            cache["policy_energy"] = results[4]

        async def _on_refresh() -> None:
            await _load_data()
            render_accuracy.refresh()
            render_decisions.refresh()
            render_preferences.refresh()
            render_pending.refresh()
            render_delegation.refresh()

        async def _search_decisions() -> None:
            q = search_state.get("query", "").strip()
            if not q:
                return
            result = await _post(
                "/companion/henninggpt/decisions/search",
                {"query": q, "user_id": "henning", "limit": 6},
            )
            cache["decisions"] = (result or {}).get("decisions", [])
            render_decisions.refresh()

        async def _submit_feedback(pred_id: str, correct: bool) -> None:
            await _post(
                f"/companion/henninggpt/predictions/{pred_id}/feedback",
                {"correct": correct},
            )
            await asyncio.gather(
                _load_data(),
            )
            render_accuracy.refresh()
            render_pending.refresh()

        async def _score_delegation_demo() -> None:
            result = await _post(
                "/companion/henninggpt/delegate",
                {
                    "action": "start EV charging at current PV surplus",
                    "context": "energy",
                    "base_confidence": 0.87,
                    "supporting_evidence": ["PV surplus 2 kW", "EV at 40% SoC"],
                },
            )
            cache["delegation_demo"] = result
            render_delegation.refresh()

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # ── Header ────────────────────────────────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("HenningGPT")
                    ui.label(
                        "Personal AI Model · Decision Memory · Preference Graph · Delegation"
                    ).style("color: #94a3b8")
                ui.button(
                    "Refresh",
                    icon="refresh",
                    on_click=_on_refresh,
                ).props("flat no-caps").style("color: #94a3b8")

            # ── Phase 3 accuracy strip ─────────────────────────────────────────
            @ui.refreshable
            def render_accuracy() -> None:
                acc = cache.get("accuracy")
                total = (acc or {}).get("total", 0)
                correct = (acc or {}).get("correct", 0)
                incorrect = (acc or {}).get("incorrect", 0)
                pending_count = (acc or {}).get("pending", 0)
                pct = (acc or {}).get("accuracy_pct", 0.0)

                acc_color = (
                    COLORS["grid_export"]
                    if pct >= 80
                    else COLORS["warning"]
                    if pct >= 60
                    else COLORS["grid_import"]
                )

                with ui.row().classes("w-full gap-4 flex-wrap"):
                    # Accuracy gauge card
                    with ui.card().classes("p-5 flex-1 min-w-[200px]").style(
                        f"border-left: 4px solid {acc_color} !important"
                    ):
                        with ui.row().classes("items-center gap-2 mb-2"):
                            ui.icon("auto_graph").style(f"color: {acc_color}")
                            ui.label("Prediction Accuracy (30d)").classes(
                                "font-bold"
                            ).style("color: #e2e8f0")
                        ui.label(f"{pct:.0f}%").classes("text-4xl font-bold").style(
                            f"color: {acc_color}"
                        )
                        with ui.element("div").style(
                            "background: #2d2d4a; height: 6px; border-radius: 3px; margin-top:6px"
                        ):
                            ui.element("div").style(
                                f"width: {min(pct, 100):.0f}%; height: 6px; "
                                f"background: {acc_color}; border-radius: 3px"
                            )

                    for icon_name, label, val, color in [
                        ("check_circle", "Correct", correct, COLORS["grid_export"]),
                        ("cancel", "Incorrect", incorrect, COLORS["grid_import"]),
                        ("schedule", "Pending", pending_count, COLORS["text_muted"]),
                        ("functions", "Total", total, COLORS["battery"]),
                    ]:
                        with ui.card().classes("p-4 flex-1 min-w-[120px] text-center"):
                            ui.icon(icon_name).classes("text-2xl").style(
                                f"color: {color}"
                            )
                            ui.label(str(val)).classes("text-3xl font-bold").style(
                                f"color: {color}"
                            )
                            ui.label(label).classes("text-xs uppercase").style(
                                "color: #64748b"
                            )

                    # Per-category breakdown
                    by_cat = (acc or {}).get("by_category", {})
                    if by_cat:
                        with ui.card().classes("p-4 flex-1 min-w-[200px]"):
                            ui.label("By Category").classes(
                                "text-xs uppercase tracking-wide mb-2"
                            ).style("color: #64748b")
                            for cat, stats in by_cat.items():
                                cat_total = stats.get("total", 0)
                                cat_correct = stats.get("correct", 0)
                                cat_pct = (
                                    round(cat_correct / cat_total * 100)
                                    if cat_total
                                    else 0
                                )
                                clr = _CTX_COLOR.get(cat, COLORS["text_muted"])
                                with ui.row().classes("items-center gap-2 mb-1"):
                                    ui.icon(_CTX_ICON.get(cat, "circle")).classes(
                                        "text-sm"
                                    ).style(f"color: {clr}")
                                    ui.label(cat).classes("text-xs flex-1").style(
                                        "color: #94a3b8"
                                    )
                                    ui.label(f"{cat_pct}%").classes(
                                        "text-xs font-bold"
                                    ).style(f"color: {clr}")

            render_accuracy()

            # ── Phase 1 — Decision memory RAG ───────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                section_title("Decision Memory")
                with ui.row().classes("gap-2 items-center"):
                    search_input = ui.input(
                        placeholder="Search decisions…"
                    ).props("dense outlined").style(
                        "width: 220px; color: #e2e8f0"
                    )
                    search_input.on(
                        "update:model-value",
                        lambda e: search_state.update({"query": e.args}),
                    )
                    ui.button(
                        "Search",
                        icon="search",
                        on_click=lambda: asyncio.create_task(_search_decisions()),
                    ).props("flat no-caps dense").style("color: #6366f1")
                    ui.button(
                        "Recent",
                        icon="history",
                        on_click=lambda: asyncio.create_task(_on_refresh()),
                    ).props("flat no-caps dense").style("color: #94a3b8")

            @ui.refreshable
            def render_decisions() -> None:
                decisions = cache["decisions"]

                if not decisions:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("memory").classes("text-4xl").style(
                            "color: #64748b"
                        )
                        ui.label(
                            "No decisions stored yet — decisions are recorded as Henning "
                            "interacts with the orchestrator."
                        ).classes("text-sm mt-2").style("color: #94a3b8")
                    return

                with ui.grid(columns=2).classes("w-full gap-3"):
                    for d in decisions:
                        conf = float(d.get("confidence", 0.7))
                        conf_color = (
                            COLORS["grid_export"]
                            if conf >= 0.8
                            else COLORS["warning"]
                            if conf >= 0.6
                            else COLORS["grid_import"]
                        )
                        created = (d.get("created_at") or "")[:10]
                        outcome = d.get("outcome")

                        with ui.card().classes("p-4").style(
                            f"border-left: 3px solid {conf_color} !important"
                        ):
                            with ui.row().classes("items-start justify-between gap-2"):
                                ui.label(d.get("decision", "")).classes(
                                    "text-sm font-semibold flex-1"
                                ).style("color: #e2e8f0; word-break: break-word")
                                ui.label(f"{conf:.0%}").classes(
                                    "text-xs font-bold"
                                ).style(f"color: {conf_color}; white-space: nowrap")

                            context_text = d.get("context", "")
                            if context_text:
                                ui.label(context_text[:80]).classes(
                                    "text-xs mt-1"
                                ).style("color: #94a3b8")

                            reasoning = d.get("reasoning", "")
                            if reasoning:
                                ui.label(f"Why: {reasoning[:100]}").classes(
                                    "text-xs mt-1 italic"
                                ).style("color: #64748b")

                            with ui.row().classes("items-center gap-2 mt-2"):
                                if created:
                                    ui.label(created).classes("text-xs").style(
                                        "color: #64748b"
                                    )
                                if outcome:
                                    ui.badge(outcome[:30], color="green").classes(
                                        "text-xs"
                                    )

            render_decisions()

            # ── Phase 2 — Preference graph ─────────────────────────────────
            section_title("Preference Graph")

            @ui.refreshable
            def render_preferences() -> None:
                prefs = cache["preferences"]

                if not prefs:
                    with ui.card().classes("w-full p-8 text-center"):
                        ui.icon("account_tree").classes("text-4xl").style(
                            "color: #64748b"
                        )
                        ui.label(
                            "No preferences learned yet — they build up as the AI "
                            "observes Henning's patterns."
                        ).classes("text-sm mt-2").style("color: #94a3b8")
                    return

                # Group by context
                by_context: dict[str, list] = {}
                for p in prefs:
                    ctx = p.get("context", "general")
                    by_context.setdefault(ctx, []).append(p)

                for ctx, nodes in sorted(by_context.items()):
                    clr = _CTX_COLOR.get(ctx, COLORS["text_muted"])
                    icon = _CTX_ICON.get(ctx, "circle")

                    with ui.card().classes("w-full p-4 mb-2"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon(icon).style(f"color: {clr}")
                            ui.label(ctx.upper()).classes("font-bold text-sm").style(
                                f"color: {clr}"
                            )
                            ui.label(f"({len(nodes)} nodes)").classes(
                                "text-xs"
                            ).style("color: #64748b")

                        with ui.grid(columns=2).classes("w-full gap-2"):
                            for node in nodes:
                                conf = float(node.get("confidence", 0.7))
                                times = int(node.get("times_confirmed", 0))
                                why = node.get("why", "")

                                with ui.element("div").classes("p-3").style(
                                    "background: #0f0f1a; border-radius: 6px; "
                                    f"border-left: 2px solid {clr}"
                                ):
                                    with ui.row().classes("items-start justify-between"):
                                        ui.label(node.get("key", "")).classes(
                                            "text-xs font-bold"
                                        ).style("color: #e2e8f0")
                                        ui.label(f"{conf:.0%}").classes(
                                            "text-xs"
                                        ).style(f"color: {clr}")
                                    ui.label(
                                        str(node.get("value", ""))[:60]
                                    ).classes("text-xs mt-1").style("color: #94a3b8")
                                    if why:
                                        ui.label(f"↳ {why[:70]}").classes(
                                            "text-xs mt-1 italic"
                                        ).style("color: #64748b")
                                    if times > 0:
                                        ui.label(f"✓ confirmed {times}×").classes(
                                            "text-xs mt-1"
                                        ).style("color: #22c55e")

            render_preferences()

            # ── Phase 3 — Pending predictions ─────────────────────────────
            with ui.row().classes("w-full items-center justify-between"):
                section_title("Pending Feedback")

            @ui.refreshable
            def render_pending() -> None:
                preds = cache["pending"]

                if not preds:
                    with ui.card().classes("w-full p-6 text-center"):
                        ui.icon("check_circle").classes("text-3xl").style(
                            "color: #22c55e"
                        )
                        ui.label(
                            "No predictions awaiting feedback — all caught up!"
                        ).classes("text-sm mt-1").style("color: #94a3b8")
                    return

                with ui.column().classes("w-full gap-2"):
                    for pred in preds:
                        pred_id = pred.get("prediction_id", "")
                        conf = float(pred.get("confidence", 0.7))
                        cat = pred.get("category", "general")
                        clr = _CTX_COLOR.get(cat, COLORS["text_muted"])
                        created = (pred.get("created_at") or "")[:10]

                        with ui.card().classes("w-full p-4").style(
                            f"border-left: 3px solid {clr} !important"
                        ):
                            with ui.row().classes("items-start gap-3 w-full"):
                                with ui.column().classes("flex-1 gap-1"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon(_CTX_ICON.get(cat, "circle")).classes(
                                            "text-sm"
                                        ).style(f"color: {clr}")
                                        ui.label(cat).classes("text-xs").style(
                                            f"color: {clr}"
                                        )
                                        ui.label(f"{conf:.0%} confidence").classes(
                                            "text-xs"
                                        ).style("color: #64748b")
                                        if created:
                                            ui.label(created).classes("text-xs").style(
                                                "color: #64748b"
                                            )
                                    ui.label(
                                        pred.get("prediction", "")[:120]
                                    ).classes("text-sm").style("color: #e2e8f0")
                                    ctx_text = pred.get("context", "")
                                    if ctx_text:
                                        ui.label(ctx_text[:80]).classes(
                                            "text-xs"
                                        ).style("color: #94a3b8")

                                with ui.row().classes("items-center gap-2"):
                                    ui.button(
                                        "Correct",
                                        icon="thumb_up",
                                        on_click=lambda p=pred_id: asyncio.create_task(
                                            _submit_feedback(p, True)
                                        ),
                                    ).props("flat no-caps dense").style(
                                        "color: #22c55e; font-size: 0.75rem"
                                    )
                                    ui.button(
                                        "Wrong",
                                        icon="thumb_down",
                                        on_click=lambda p=pred_id: asyncio.create_task(
                                            _submit_feedback(p, False)
                                        ),
                                    ).props("flat no-caps dense").style(
                                        "color: #ef4444; font-size: 0.75rem"
                                    )

            render_pending()

            # ── Phase 4 — Delegation mode ──────────────────────────────────
            section_title("Delegation Engine")

            @ui.refreshable
            def render_delegation() -> None:
                policy = cache.get("policy_energy")
                demo = cache.get("delegation_demo")

                with ui.row().classes("w-full gap-4 items-start flex-wrap"):
                    # Current policy card
                    with ui.card().classes("p-5 flex-1 min-w-[250px]"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("settings_suggest").style(
                                f"color: {COLORS['primary']}"
                            )
                            ui.label("Energy Policy").classes("font-bold").style(
                                "color: #e2e8f0"
                            )

                        if policy:
                            thresh = float(policy.get("threshold", 0.85))
                            auto_send = bool(policy.get("auto_send", False))
                            always_confirm = bool(policy.get("always_confirm", False))

                            thresh_color = (
                                COLORS["grid_export"]
                                if thresh <= 0.80
                                else COLORS["warning"]
                                if thresh <= 0.90
                                else COLORS["grid_import"]
                            )

                            ui.label(f"{thresh:.0%}").classes(
                                "text-3xl font-bold"
                            ).style(f"color: {thresh_color}")
                            ui.label("confidence threshold").classes("text-xs").style(
                                "color: #64748b"
                            )

                            with ui.row().classes("gap-2 mt-3 flex-wrap"):
                                status_color = (
                                    COLORS["grid_export"] if auto_send else COLORS["grid_import"]
                                )
                                ui.badge(
                                    "auto-send ON" if auto_send else "auto-send OFF",
                                    color="green" if auto_send else "red",
                                ).classes("text-xs")
                                if always_confirm:
                                    ui.badge("always-confirm", color="orange").classes(
                                        "text-xs"
                                    )
                        else:
                            ui.label("Policy unavailable — orchestrator offline?").classes(
                                "text-sm"
                            ).style("color: #64748b")

                    # Delegation sandbox
                    with ui.card().classes("p-5 flex-1 min-w-[300px]"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("robot").style(f"color: {COLORS['ev']}")
                            ui.label("Delegation Sandbox").classes("font-bold").style(
                                "color: #e2e8f0"
                            )
                        ui.label(
                            "Score: 'start EV charging at current PV surplus'"
                        ).classes("text-xs mb-2").style("color: #94a3b8")
                        ui.button(
                            "Run Scoring",
                            icon="play_arrow",
                            on_click=lambda: asyncio.create_task(
                                _score_delegation_demo()
                            ),
                        ).props("flat no-caps").style("color: #a855f7")

                        if demo:
                            should = demo.get("should_delegate", False)
                            conf = demo.get("confidence", 0.0)
                            thresh = demo.get("threshold", 0.85)
                            result_clr = (
                                COLORS["grid_export"] if should else COLORS["warning"]
                            )

                            with ui.row().classes("items-center gap-3 mt-4"):
                                ui.icon(
                                    "check_circle" if should else "pending"
                                ).classes("text-3xl").style(f"color: {result_clr}")
                                with ui.column().classes("gap-0"):
                                    ui.label(
                                        "DELEGATE" if should else "PROPOSE"
                                    ).classes("font-bold").style(f"color: {result_clr}")
                                    ui.label(
                                        f"Confidence: {conf:.0%} / Threshold: {thresh:.0%}"
                                    ).classes("text-xs").style("color: #94a3b8")

                            reasoning = demo.get("reasoning", "")
                            if reasoning:
                                ui.label(reasoning).classes("text-xs mt-2 italic").style(
                                    "color: #64748b"
                                )

                            confirm_msg = demo.get("confirmation_message")
                            if confirm_msg:
                                ui.label(confirm_msg).classes("text-xs mt-2 p-2").style(
                                    "background: #0f0f1a; border-radius: 4px; "
                                    "color: #94a3b8; font-style: italic"
                                )

            render_delegation()

            # ── Auto-refresh every 5 minutes ──────────────────────────────
            ui.timer(300.0, _on_refresh)
