"""Family OS dashboard page — shared system and Nicole view (FR #4 / item #41).

Two tabs:
  - Family Dashboard — full view (meals, calendar, grocery, energy, votes/alignment)
  - Nicole's View    — simplified German-greeting view for Nicole
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


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

_ENERGY_COLOR = {
    "all_good": COLORS["grid_export"],   # green
    "normal":   COLORS["warning"],       # amber
    "high_usage": COLORS["grid_import"], # red
    "unknown":  COLORS["text_dim"],
}

_ENERGY_ICON = {
    "all_good":   "check_circle",
    "normal":     "bolt",
    "high_usage": "warning",
    "unknown":    "help_outline",
}

_TYPE_ICON = {
    "vacation": "flight_takeoff",
    "purchase": "shopping_cart",
    "project":  "construction",
}

_TYPE_COLOR = {
    "vacation": "#a855f7",
    "purchase": "#3b82f6",
    "project":  "#f97316",
}


def _energy_card(energy: dict[str, Any]) -> None:
    status = energy.get("status", "unknown")
    color  = _ENERGY_COLOR.get(status, COLORS["text_dim"])
    icon   = _ENERGY_ICON.get(status, "help_outline")
    label_map = {
        "all_good":   "All Good",
        "normal":     "Normal",
        "high_usage": "High Usage",
        "unknown":    "Unknown",
    }
    label = label_map.get(status, status.replace("_", " ").title())
    detail = energy.get("detail", "")
    with ui.card().classes("p-4").style(
        f"border-left: 4px solid {color} !important; background: {COLORS['card']}"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon(icon).classes("text-3xl").style(f"color: {color}")
            with ui.column().classes("gap-0"):
                ui.label("House Energy").classes("text-xs uppercase tracking-wide").style(
                    f"color: {COLORS['text_muted']}"
                )
                ui.label(label).classes("text-xl font-bold").style(f"color: {color}")
                if detail:
                    ui.label(detail).classes("text-sm").style(f"color: {COLORS['text_dim']}")


def _meal_card(meals: dict[str, Any]) -> None:
    with ui.card().classes("p-4 w-full").style(f"background: {COLORS['card']}"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("restaurant").style(f"color: {COLORS['solar']}")
            ui.label("Today's Meals").classes("text-sm font-semibold").style(
                f"color: {COLORS['text']}"
            )
        if meals.get("error") or meals.get("note"):
            ui.label(meals.get("error") or meals.get("note", "Unavailable")).classes(
                "text-sm"
            ).style(f"color: {COLORS['text_dim']}")
            return
        meal_list = meals.get("meals", [])
        if not meal_list:
            # Some planners return flat keys like breakfast/lunch/dinner
            meal_list = [
                {"name": v, "type": k}
                for k, v in meals.items()
                if k in ("breakfast", "lunch", "dinner", "snack") and v
            ]
        if not meal_list:
            ui.label("No meals planned").classes("text-sm").style(
                f"color: {COLORS['text_dim']}"
            )
            return
        for meal in meal_list:
            name = meal.get("name") or meal.get("title") or str(meal)
            meal_type = meal.get("type", "")
            with ui.row().classes("items-center gap-2"):
                ui.icon("circle").classes("text-xs").style(f"color: {COLORS['solar']}")
                txt = f"{meal_type.capitalize()}: {name}" if meal_type else name
                ui.label(txt).classes("text-sm").style(f"color: {COLORS['text']}")


def _calendar_card(events: list[dict[str, Any]]) -> None:
    with ui.card().classes("p-4 w-full").style(f"background: {COLORS['card']}"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("event").style(f"color: {COLORS['primary']}")
            ui.label("Calendar").classes("text-sm font-semibold").style(
                f"color: {COLORS['text']}"
            )
        if not events:
            ui.label("No upcoming events").classes("text-sm").style(
                f"color: {COLORS['text_dim']}"
            )
            return
        for ev in events[:6]:
            summary = ev.get("summary") or ev.get("title") or "Event"
            start   = ev.get("start") or ev.get("date") or ""
            with ui.row().classes("items-center gap-2 py-0.5"):
                ui.icon("calendar_today").classes("text-xs").style(
                    f"color: {COLORS['primary']}"
                )
                with ui.column().classes("gap-0"):
                    ui.label(summary).classes("text-sm").style(f"color: {COLORS['text']}")
                    if start:
                        ui.label(str(start)[:10]).classes("text-xs").style(
                            f"color: {COLORS['text_dim']}"
                        )


def _grocery_card(grocery: dict[str, Any]) -> None:
    items = grocery.get("items", [])
    total = grocery.get("total", len(items))
    note  = grocery.get("note") or grocery.get("error") or ""
    with ui.card().classes("p-4 w-full").style(f"background: {COLORS['card']}"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("shopping_basket").style(f"color: {COLORS['grid_export']}")
            ui.label(f"Grocery List ({total})").classes("text-sm font-semibold").style(
                f"color: {COLORS['text']}"
            )
        if note and not items:
            ui.label(note).classes("text-sm").style(f"color: {COLORS['text_dim']}")
            return
        if not items:
            ui.label("List is empty").classes("text-sm").style(
                f"color: {COLORS['text_dim']}"
            )
            return
        for item in items[:10]:
            content = item.get("content") or item.get("name") or item.get("title") or str(item)
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_box_outline_blank").classes("text-sm").style(
                    f"color: {COLORS['grid_export']}"
                )
                ui.label(content).classes("text-sm").style(f"color: {COLORS['text']}")
        if total > 10:
            ui.label(f"… and {total - 10} more").classes("text-xs").style(
                f"color: {COLORS['text_dim']}"
            )


def _alignment_bar(score: float | None, label: str) -> None:
    """Render an alignment percentage bar."""
    if score is None:
        ui.label("needs votes").classes("text-xs").style(f"color: {COLORS['text_dim']}")
        return
    pct = int(score * 100)
    if pct >= 90:
        color = COLORS["grid_export"]
    elif pct >= 70:
        color = COLORS["warning"]
    else:
        color = COLORS["grid_import"]
    with ui.column().classes("gap-1 w-full"):
        with ui.row().classes("justify-between w-full"):
            ui.label(label).classes("text-xs").style(f"color: {color}")
            ui.label(f"{pct}%").classes("text-xs font-bold").style(f"color: {color}")
        with ui.element("div").classes("w-full rounded-full").style(
            f"height: 6px; background: {COLORS['border']}"
        ):
            ui.element("div").style(
                f"height: 6px; width: {pct}%; background: {color}; border-radius: 9999px"
            )


def _votes_panel(
    items: list[dict[str, Any]],
    on_vote: Any,  # callable(item_id, user, vote, importance, title, item_type)
) -> None:
    """Render shared items + vote submission form."""
    if not items:
        with ui.card().classes("p-6 w-full text-center").style(
            f"background: {COLORS['card']}"
        ):
            ui.icon("flight_takeoff").classes("text-4xl").style(
                f"color: {COLORS['text_dim']}"
            )
            ui.label("No shared items yet — add one below").classes("text-sm").style(
                f"color: {COLORS['text_muted']}"
            )
    else:
        for item in items:
            itype = item.get("type", "vacation")
            color = _TYPE_COLOR.get(itype, COLORS["primary"])
            icon  = _TYPE_ICON.get(itype, "star")
            score = item.get("alignment_score")
            alabel = item.get("alignment_label", "")
            votes  = item.get("votes", {})

            with ui.card().classes("p-4 w-full").style(
                f"border-left: 4px solid {color} !important; background: {COLORS['card']}"
            ):
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.icon(icon).classes("text-lg").style(f"color: {color}")
                    ui.label(item.get("title", item.get("id", "?"))).classes(
                        "text-base font-semibold"
                    ).style(f"color: {COLORS['text']}")
                    ui.badge(itype.capitalize()).style(
                        f"background: {color}20; color: {color}; font-size: 11px"
                    )

                _alignment_bar(score, alabel)

                # Per-user votes summary
                if votes:
                    with ui.row().classes("gap-4 mt-1"):
                        for user, v in votes.items():
                            vote_val = v.get("vote", "?")
                            imp_val  = v.get("importance", "?")
                            ui.label(
                                f"{user}: {vote_val}/10 (imp {imp_val})"
                            ).classes("text-xs").style(f"color: {COLORS['text_muted']}")

    # --- Vote submission form ---
    with ui.card().classes("p-4 w-full").style(f"background: {COLORS['card']}"):
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("how_to_vote").style(f"color: {COLORS['primary']}")
            ui.label("Cast a Vote").classes("text-sm font-semibold").style(
                f"color: {COLORS['text']}"
            )
        with ui.grid(columns=2).classes("gap-3 w-full"):
            item_id_input  = ui.input("Item ID (slug)").classes("w-full")
            title_input    = ui.input("Title (for new items)").classes("w-full")
            user_select    = ui.select(["Henning", "Nicole"], label="Voter").classes("w-full")
            type_select    = ui.select(
                ["vacation", "purchase", "project"], label="Type", value="vacation"
            ).classes("w-full")
            vote_slider    = ui.slider(min=1, max=10, value=7).classes("w-full")
            imp_slider     = ui.slider(min=1, max=10, value=5).classes("w-full")

        with ui.row().classes("items-center gap-4 mt-1"):
            ui.label("").bind_text_from(vote_slider, "value", lambda v: f"Vote: {v}/10").style(
                f"color: {COLORS['text_muted']}"
            ).classes("text-sm")
            ui.label("").bind_text_from(imp_slider, "value", lambda v: f"Importance: {v}/10").style(
                f"color: {COLORS['text_muted']}"
            ).classes("text-sm")

        async def _submit() -> None:
            if not item_id_input.value:
                ui.notify("Item ID is required", type="warning")
                return
            if not user_select.value:
                ui.notify("Select a voter", type="warning")
                return
            await on_vote(
                item_id=item_id_input.value.strip().lower().replace(" ", "-"),
                user=user_select.value,
                vote=int(vote_slider.value),
                importance=int(imp_slider.value),
                title=title_input.value.strip(),
                item_type=type_select.value,
            )

        ui.button("Submit Vote", icon="send", on_click=_submit).props(
            "color=primary"
        ).classes("mt-2")


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------


def setup(state: "DashboardState", settings: "DashboardSettings") -> None:
    """Register the /family and /family/nicole pages."""

    base    = settings.orchestrator_url
    api_key = settings.orchestrator_api_key

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers() -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if api_key:
            h["X-API-Key"] = api_key
        return h

    async def _get(path: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}{path}", headers=_headers())
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    async def _post(path: str, payload: dict) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}{path}", json=payload, headers=_headers())
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return None

    # ── Full Family Dashboard ─────────────────────────────────────────────────

    @ui.page("/family")
    async def family_page() -> None:
        create_page_layout("/family")

        cache: dict[str, Any] = {
            "dashboard": {},
            "votes": [],
        }

        async def _load_data() -> None:
            results = await asyncio.gather(
                _get("/api/v1/family"),
                _get("/api/v1/family/votes"),
            )
            cache["dashboard"] = results[0] or {}
            votes_resp          = results[1] or {}
            cache["votes"]      = votes_resp.get("items", [])

        async def _on_vote(
            item_id: str,
            user: str,
            vote: int,
            importance: int,
            title: str,
            item_type: str,
        ) -> None:
            result = await _post(
                "/api/v1/family/votes",
                {
                    "item_id":   item_id,
                    "user":      user,
                    "vote":      vote,
                    "importance": importance,
                    "title":     title,
                    "item_type": item_type,
                },
            )
            if result:
                ui.notify(
                    f"Vote saved! {result.get('alignment_label', '')}",
                    type="positive",
                )
            else:
                ui.notify("Failed to save vote", type="negative")
            await _load_data()
            render_main.refresh()

        async def _on_refresh() -> None:
            await _load_data()
            render_main.refresh()

        await _load_data()

        with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):

            # Header
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    section_title("Family OS")
                    ui.label("Shared System · Meals · Calendar · Grocery · Vacation Planner").style(
                        f"color: {COLORS['text_muted']}"
                    )
                ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                    "flat color=primary"
                )

            @ui.refreshable
            def render_main() -> None:
                dash    = cache["dashboard"]
                energy  = dash.get("energy_status", {})
                meals   = dash.get("meals_today", {})
                events  = dash.get("calendar_events", [])
                grocery = dash.get("grocery_list", {})
                items   = cache["votes"]
                signals = dash.get("context_signals", {})

                # Row 1: Energy + context signals
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    with ui.element("div").classes("flex-1 min-w-[200px]"):
                        _energy_card(energy)
                    if signals:
                        with ui.card().classes("p-4 flex-1 min-w-[200px]").style(
                            f"background: {COLORS['card']}"
                        ):
                            with ui.row().classes("items-center gap-2 mb-1"):
                                ui.icon("schedule").style(f"color: {COLORS['text_muted']}")
                                ui.label("Context").classes("text-sm font-semibold").style(
                                    f"color: {COLORS['text']}"
                                )
                            day  = signals.get("day_of_week", "")
                            time = signals.get("time_of_day", "")
                            wknd = signals.get("is_weekend", False)
                            ui.label(f"{day}  {time}{'  · Weekend' if wknd else ''}").classes(
                                "text-sm"
                            ).style(f"color: {COLORS['text_muted']}")

                # Row 2: Meals + Grocery
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    with ui.element("div").classes("flex-1 min-w-[260px]"):
                        _meal_card(meals)
                    with ui.element("div").classes("flex-1 min-w-[260px]"):
                        _grocery_card(grocery)

                # Row 3: Calendar
                with ui.element("div").classes("w-full"):
                    _calendar_card(events)

                # Row 4: Vacation Planner / Shared Items
                section_title("Vacation Planner & Shared Decisions")
                _votes_panel(items, on_vote=_on_vote)

            render_main()
            ui.timer(60.0, _on_refresh)

    # ── Nicole's Simplified View ──────────────────────────────────────────────

    @ui.page("/family/nicole")
    async def nicole_page() -> None:
        create_page_layout("/family")

        cache: dict[str, Any] = {"nicole": {}}

        async def _load() -> None:
            result = await _get("/api/v1/family/nicole")
            cache["nicole"] = result or {}

        async def _on_refresh() -> None:
            await _load()
            render_nicole.refresh()

        await _load()

        with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-6"):

            @ui.refreshable
            def render_nicole() -> None:
                d = cache["nicole"]
                if not d:
                    with ui.card().classes("p-8 text-center w-full").style(
                        f"background: {COLORS['card']}"
                    ):
                        ui.icon("wifi_off").classes("text-5xl").style(
                            f"color: {COLORS['text_dim']}"
                        )
                        ui.label("Family OS unavailable").style(
                            f"color: {COLORS['text_muted']}"
                        )
                    return

                greeting = d.get("greeting", "Hallo, Nicole!")
                date_str = d.get("date", "")
                energy   = d.get("energy_status", {})
                meals    = d.get("meals_today", {})
                events   = d.get("todays_events", [])
                grocery  = d.get("grocery_list", {})
                vacation = d.get("next_shared_vacation")

                # Greeting card
                with ui.card().classes("p-6 w-full text-center").style(
                    f"background: {COLORS['card']}; border: 1px solid {COLORS['primary']}33"
                ):
                    ui.label(greeting).classes("text-3xl font-bold").style(
                        f"color: {COLORS['primary']}"
                    )
                    if date_str:
                        ui.label(date_str).classes("text-sm mt-1").style(
                            f"color: {COLORS['text_muted']}"
                        )

                # Energy status
                _energy_card(energy)

                # Meals
                _meal_card(meals)

                # Today's calendar events
                _calendar_card(events)

                # Grocery
                _grocery_card(grocery)

                # Top agreed vacation
                if vacation:
                    vcolor = _TYPE_COLOR["vacation"]
                    with ui.card().classes("p-4 w-full").style(
                        f"border-left: 4px solid {vcolor} !important; background: {COLORS['card']}"
                    ):
                        with ui.row().classes("items-center gap-2 mb-2"):
                            ui.icon("flight_takeoff").style(f"color: {vcolor}")
                            ui.label("Next Shared Trip").classes("text-sm font-semibold").style(
                                f"color: {COLORS['text']}"
                            )
                        ui.label(vacation.get("title", "")).classes(
                            "text-xl font-bold"
                        ).style(f"color: {vcolor}")
                        _alignment_bar(
                            vacation.get("alignment_score"),
                            vacation.get("alignment_label", ""),
                        )

            render_nicole()
            ui.timer(120.0, _on_refresh)

            ui.button("Refresh", icon="refresh", on_click=_on_refresh).props(
                "flat color=primary"
            )
            ui.link("← Full Family Dashboard", "/family").style(
                f"color: {COLORS['text_dim']}; font-size: 13px"
            )
