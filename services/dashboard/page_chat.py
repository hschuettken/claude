"""Chat page — talk to the orchestrator via MQTT."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nicegui import ui

from layout import COLORS, create_page_layout

if TYPE_CHECKING:
    from shared.mqtt_client import MQTTClient

    from config import DashboardSettings
    from state import DashboardState


def setup(
    state: DashboardState,
    settings: DashboardSettings,
    mqtt: MQTTClient,
) -> None:
    """Register the chat page."""

    @ui.page("/chat")
    def chat_page() -> None:
        create_page_layout("/chat")

        with ui.column().classes("w-full max-w-4xl mx-auto p-6 gap-4").style(
            "height: calc(100vh - 80px)"
        ):
            with ui.row().classes("items-center gap-2"):
                ui.icon("chat").style(f"color: {COLORS['primary']}")
                ui.label("Chat with Orchestrator").classes(
                    "text-xl font-bold"
                ).style("color: #e2e8f0")

            # Chat message area
            chat_scroll = (
                ui.scroll_area()
                .classes("flex-1 w-full")
                .style(
                    "background: #0f0f1a; border: 1px solid #2d2d4a; border-radius: 8px"
                )
            )

            @ui.refreshable
            def chat_messages() -> None:
                with chat_scroll:
                    with ui.column().classes("w-full p-4 gap-3"):
                        if not state.chat_messages:
                            with ui.column().classes(
                                "w-full items-center justify-center py-16"
                            ):
                                ui.icon("smart_toy").style(
                                    "color: #2d2d4a; font-size: 4rem"
                                )
                                ui.label("Start a conversation").classes(
                                    "text-lg mt-2"
                                ).style("color: #64748b")
                                ui.label(
                                    "Ask about energy, PV forecast, EV charging, or anything about your home."
                                ).classes("text-sm").style("color: #4a4a6a")
                        else:
                            for msg in state.chat_messages:
                                _render_message(msg)

                        if state.chat_pending:
                            _render_typing_indicator()

            chat_messages()

            # Input area
            with ui.row().classes("w-full gap-2 items-end"):
                msg_input = (
                    ui.textarea(placeholder="Type a message...")
                    .classes("flex-1")
                    .props(
                        'outlined dense dark color="indigo-4" autogrow '
                        'input-style="color: #e2e8f0" maxlength="2000"'
                    )
                    .style("max-height: 120px")
                )

                async def send_message() -> None:
                    text = msg_input.value.strip()
                    if not text or state.chat_pending:
                        return

                    # Add user message
                    state.add_chat_message("user", text)
                    msg_input.value = ""

                    # Send via MQTT
                    request_id = state.send_chat_request()
                    mqtt.publish(
                        "homelab/orchestrator/command/dashboard",
                        {
                            "command": "chat",
                            "message": text,
                            "request_id": request_id,
                            "user_name": settings.dashboard_user_name,
                        },
                    )

                    chat_messages.refresh()

                send_btn = (
                    ui.button(icon="send", on_click=send_message)
                    .props('round color="indigo-6"')
                    .style("width: 48px; height: 48px")
                )

                # Enter to send (Shift+Enter for newline)
                msg_input.on(
                    "keydown.enter",
                    js_handler="""
                    (e) => {
                        if (!e.shiftKey) {
                            e.preventDefault();
                            document.querySelector('[data-send-btn]')?.click();
                        }
                    }
                    """,
                )
                send_btn.props('data-send-btn=""')

            # Quick prompts
            with ui.row().classes("gap-2 flex-wrap"):
                for prompt_text, prompt_icon in [
                    ("Energy status", "bolt"),
                    ("PV forecast", "wb_sunny"),
                    ("EV charging status", "electric_car"),
                    ("Weather forecast", "cloud"),
                ]:

                    def make_click(p: str) -> None:
                        async def click() -> None:
                            msg_input.value = p
                            await send_message()

                        return click

                    ui.button(
                        prompt_text,
                        icon=prompt_icon,
                        on_click=make_click(prompt_text),
                    ).props('flat dense no-caps color="grey-6" size="sm"')

            # Auto-refresh chat to show new messages and typing state
            ui.timer(1.0, chat_messages.refresh)


def _render_message(msg: dict) -> None:
    """Render a single chat message bubble."""
    is_user = msg["role"] == "user"
    align = "items-end" if is_user else "items-start"
    bg = "#2d2d6a" if is_user else "#1e1e2e"
    border = "#4a4a8a" if is_user else "#2d2d4a"
    name = "You" if is_user else "Orchestrator"
    icon = "person" if is_user else "smart_toy"
    name_color = COLORS["primary"] if is_user else COLORS["solar"]

    ts = msg.get("timestamp", 0)
    time_str = time.strftime("%H:%M", time.localtime(ts)) if ts else ""

    with ui.column().classes(f"w-full {align}"):
        with ui.card().classes("p-3 max-w-[80%]").style(
            f"background: {bg} !important; border: 1px solid {border} !important"
        ):
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon(icon).style(f"color: {name_color}; font-size: 1rem")
                ui.label(name).classes("text-xs font-bold").style(
                    f"color: {name_color}"
                )
                ui.space()
                ui.label(time_str).classes("text-xs").style("color: #4a4a6a")

            ui.markdown(msg["content"]).classes("text-sm").style("color: #e2e8f0")


def _render_typing_indicator() -> None:
    """Render a typing/thinking indicator."""
    with ui.column().classes("w-full items-start"):
        with ui.card().classes("p-3").style(
            "background: #1e1e2e !important; border: 1px solid #2d2d4a !important"
        ):
            with ui.row().classes("items-center gap-2"):
                ui.icon("smart_toy").style(
                    f"color: {COLORS['solar']}; font-size: 1rem"
                )
                ui.label("Orchestrator").classes("text-xs font-bold").style(
                    f"color: {COLORS['solar']}"
                )

            with ui.row().classes("items-center gap-1 mt-1"):
                ui.spinner("dots", size="sm", color="grey")
                ui.label("Thinking...").classes("text-sm").style("color: #64748b")
