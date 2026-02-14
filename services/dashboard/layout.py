"""Shared page layout — header, navigation, and global styles."""

from __future__ import annotations

from nicegui import ui

# Color palette used across all pages
COLORS = {
    "bg": "#0a0a14",
    "card": "#1a1a2e",
    "border": "#2d2d4a",
    "text": "#e2e8f0",
    "text_muted": "#94a3b8",
    "text_dim": "#64748b",
    "solar": "#eab308",
    "grid_export": "#22c55e",
    "grid_import": "#ef4444",
    "battery": "#3b82f6",
    "house": "#f97316",
    "ev": "#a855f7",
    "primary": "#6366f1",
    "online": "#22c55e",
    "offline": "#ef4444",
    "warning": "#f59e0b",
}

_GLOBAL_CSS = """
<style>
    body { background: #0a0a14 !important; }
    .nicegui-content { padding: 0 !important; }
    .q-card { background: #1a1a2e !important; border: 1px solid #2d2d4a !important; }
    .q-header { background: #0f0f1a !important; border-bottom: 1px solid #2d2d4a !important; }
    .metric-card { transition: transform 0.15s ease, box-shadow 0.15s ease; }
    .metric-card:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }
    .nav-btn { opacity: 0.7; transition: opacity 0.2s; }
    .nav-btn:hover { opacity: 1; }
    .chat-container { display: flex; flex-direction: column; }
    .chat-scroll { flex: 1; overflow-y: auto; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0a0a14; }
    ::-webkit-scrollbar-thumb { background: #2d2d4a; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #3d3d5a; }
</style>
"""

NAV_ITEMS = [
    ("/", "dashboard", "Dashboard"),
    ("/services", "dns", "Services"),
    ("/controls", "tune", "Controls"),
    ("/chat", "chat", "Chat"),
]


def create_page_layout(active_path: str = "/") -> None:
    """Set up the shared page layout with header and navigation."""
    ui.colors(
        primary="#6366f1",
        secondary="#a855f7",
        accent="#eab308",
        positive="#22c55e",
        negative="#ef4444",
        info="#3b82f6",
        warning="#f97316",
    )

    ui.add_head_html(_GLOBAL_CSS)

    with ui.header().classes("px-4 py-2"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.icon("solar_power").classes("text-2xl").style("color: #6366f1")
            ui.label("Homelab").classes("text-xl font-bold ml-1").style(
                "color: #e2e8f0"
            )
            ui.space()
            for href, icon, label in NAV_ITEMS:
                is_active = href == active_path
                color = "#6366f1" if is_active else "#94a3b8"
                ui.button(
                    label,
                    icon=icon,
                    on_click=lambda h=href: ui.navigate.to(h),
                ).props("flat no-caps").classes("nav-btn").style(f"color: {color}")


def section_title(text: str) -> None:
    """Render a section heading."""
    ui.label(text).classes("text-xl font-bold").style("color: #e2e8f0")


def metric_card(
    icon: str,
    title: str,
    value: str,
    unit: str,
    color: str,
    subtitle: str = "",
) -> None:
    """Render a metric card with colored left border."""
    with ui.card().classes("p-4 flex-1 min-w-[170px] metric-card").style(
        f"border-left: 4px solid {color} !important"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon).style(f"color: {color}")
            ui.label(title).classes("text-xs uppercase tracking-wide").style(
                "color: #94a3b8"
            )
        ui.label(value).classes("text-3xl font-bold mt-1").style(f"color: {color}")
        ui.label(unit).classes("text-sm").style("color: #64748b")
        if subtitle:
            ui.label(subtitle).classes("text-xs mt-1").style("color: #94a3b8")
