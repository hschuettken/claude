"""HA entity controls page — change settings, trigger actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from layout import COLORS, create_page_layout, section_title

if TYPE_CHECKING:
    from shared.ha_client import HomeAssistantClient
    from shared.mqtt_client import MQTTClient

    from config import DashboardSettings
    from state import DashboardState


def setup(
    state: DashboardState,
    settings: DashboardSettings,
    ha: HomeAssistantClient,
    mqtt: MQTTClient,
) -> None:
    """Register the controls page."""

    @ui.page("/controls")
    def controls_page() -> None:
        create_page_layout("/controls")

        with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-6"):
            # === EV Charging Controls ===
            section_title("EV Charging Controls")

            with ui.card().classes("w-full p-5"):
                with ui.row().classes("items-center gap-2 mb-4"):
                    ui.icon("electric_car").style(f"color: {COLORS['ev']}")
                    ui.label("Wallbox & Charging").classes(
                        "text-lg font-bold"
                    ).style("color: #e2e8f0")

                with ui.column().classes("w-full gap-4"):
                    # Charge mode select
                    with ui.row().classes("items-center gap-4 w-full"):
                        ui.label("Charge Mode").classes("text-sm w-40").style(
                            "color: #94a3b8"
                        )
                        mode_options = state.get_entity_options(
                            settings.ev_charge_mode_entity
                        )
                        if not mode_options:
                            mode_options = [
                                "Off",
                                "PV Surplus",
                                "Smart",
                                "Eco",
                                "Fast",
                                "Manual",
                            ]
                        current_mode = state.get_entity_state(
                            settings.ev_charge_mode_entity
                        )
                        mode_select = ui.select(
                            mode_options,
                            value=current_mode if current_mode in mode_options else None,
                        ).classes("flex-1").props(
                            'outlined dense dark color="deep-purple-4"'
                        )

                        async def on_mode_change(e: Any) -> None:
                            await _set_input_select(
                                ha,
                                settings.ev_charge_mode_entity,
                                e.value,
                                "Charge mode",
                            )

                        mode_select.on_value_change(on_mode_change)

                    # Target SoC slider
                    with ui.row().classes("items-center gap-4 w-full"):
                        ui.label("Target SoC").classes("text-sm w-40").style(
                            "color: #94a3b8"
                        )
                        current_soc = state.get_entity_float(
                            settings.ev_target_soc_entity, 80
                        )
                        soc_label = ui.label(f"{current_soc:.0f}%").classes(
                            "text-lg font-bold w-16 text-right"
                        ).style(f"color: {COLORS['ev']}")
                        soc_slider = (
                            ui.slider(min=20, max=100, step=5, value=current_soc)
                            .classes("flex-1")
                            .props('color="deep-purple-4" label-always')
                        )

                        def on_soc_label(e: Any) -> None:
                            soc_label.text = f"{e.value:.0f}%"

                        soc_slider.on_value_change(on_soc_label)

                        async def on_soc_commit() -> None:
                            await _set_input_number(
                                ha,
                                settings.ev_target_soc_entity,
                                soc_slider.value,
                                "Target SoC",
                            )

                        ui.button(
                            "Set", on_click=on_soc_commit
                        ).props('flat dense color="deep-purple-4"')

                    # Departure time
                    with ui.row().classes("items-center gap-4 w-full"):
                        ui.label("Departure Time").classes("text-sm w-40").style(
                            "color: #94a3b8"
                        )
                        dep_state = state.get_entity_state(
                            settings.ev_departure_time_entity
                        )
                        dep_val = dep_state if dep_state not in ("unknown", "unavailable") else "07:00"
                        dep_input = ui.input(
                            value=dep_val,
                        ).classes("flex-1").props(
                            'outlined dense dark color="deep-purple-4"'
                        )

                        async def on_dep_change() -> None:
                            val = dep_input.value
                            await _set_input_datetime(
                                ha,
                                settings.ev_departure_time_entity,
                                val,
                                "Departure time",
                            )

                        ui.button(
                            "Set", on_click=on_dep_change
                        ).props('flat dense color="deep-purple-4"')

                    # Full by morning toggle
                    with ui.row().classes("items-center gap-4 w-full"):
                        ui.label("Full by Morning").classes("text-sm w-40").style(
                            "color: #94a3b8"
                        )
                        fbm_state = state.get_entity_state(
                            settings.ev_full_by_morning_entity
                        )
                        fbm_switch = ui.switch(
                            value=fbm_state == "on",
                        ).props('color="deep-purple-4"')

                        async def on_fbm_change(e: Any) -> None:
                            service = "turn_on" if e.value else "turn_off"
                            try:
                                await ha.call_service(
                                    "input_boolean",
                                    service,
                                    {"entity_id": settings.ev_full_by_morning_entity},
                                )
                                ui.notify(
                                    f"Full by Morning {'enabled' if e.value else 'disabled'}",
                                    type="positive",
                                )
                            except Exception as exc:
                                ui.notify(f"Failed: {exc}", type="negative")

                        fbm_switch.on_value_change(on_fbm_change)

            # === Quick Actions ===
            section_title("Quick Actions")

            with ui.card().classes("w-full p-5"):
                with ui.row().classes("items-center gap-2 mb-4"):
                    ui.icon("bolt").style(f"color: {COLORS['warning']}")
                    ui.label("Service Commands").classes(
                        "text-lg font-bold"
                    ).style("color: #e2e8f0")

                with ui.row().classes("gap-3 flex-wrap"):

                    def _action_btn(
                        label: str,
                        icon: str,
                        service: str,
                        command: str,
                        color: str = "indigo-6",
                    ) -> None:
                        def send() -> None:
                            mqtt.publish(
                                f"homelab/orchestrator/command/{service}",
                                {"command": command},
                            )
                            ui.notify(
                                f"Sent '{command}' to {service}", type="info"
                            )

                        ui.button(label, icon=icon, on_click=send).props(
                            f'color="{color}" no-caps'
                        )

                    _action_btn(
                        "Refresh PV Forecast",
                        "wb_sunny",
                        "pv-forecast",
                        "refresh",
                        "amber-8",
                    )
                    _action_btn(
                        "Retrain PV Model",
                        "model_training",
                        "pv-forecast",
                        "retrain",
                        "amber-8",
                    )
                    _action_btn(
                        "Refresh EV Charging",
                        "electric_car",
                        "smart-ev-charging",
                        "refresh",
                        "deep-purple-6",
                    )
                    _action_btn(
                        "Refresh EV Plan",
                        "route",
                        "ev-forecast",
                        "refresh",
                        "deep-purple-6",
                    )
                    _action_btn(
                        "Refresh Vehicle Data",
                        "directions_car",
                        "ev-forecast",
                        "refresh_vehicle",
                        "deep-purple-6",
                    )

            # === Safe Mode ===
            section_title("Safety")

            with ui.card().classes("w-full p-5"):
                with ui.row().classes("items-center gap-4 w-full"):
                    ui.icon("shield").style("color: #f59e0b")
                    ui.label("Global Safe Mode").classes("text-sm").style(
                        "color: #e2e8f0"
                    )
                    ui.space()
                    safe_state = state.get_entity_state(settings.safe_mode_entity_id)
                    safe_switch = ui.switch(
                        value=safe_state == "on",
                    ).props('color="amber-8"')

                    async def on_safe_toggle(e: Any) -> None:
                        service = "turn_on" if e.value else "turn_off"
                        try:
                            await ha.call_service(
                                "input_boolean",
                                service,
                                {"entity_id": settings.safe_mode_entity_id},
                            )
                            ui.notify(
                                f"Safe Mode {'enabled' if e.value else 'disabled'}",
                                type="warning" if e.value else "positive",
                            )
                        except Exception as exc:
                            ui.notify(f"Failed: {exc}", type="negative")

                    safe_switch.on_value_change(on_safe_toggle)

                ui.label(
                    "When enabled, all services continue monitoring but block write actions."
                ).classes("text-xs mt-1").style("color: #64748b")


async def _set_input_select(
    ha: HomeAssistantClient, entity_id: str, option: str, label: str,
) -> None:
    try:
        await ha.call_service(
            "input_select",
            "select_option",
            {"entity_id": entity_id, "option": option},
        )
        ui.notify(f"{label} set to {option}", type="positive")
    except Exception as exc:
        ui.notify(f"Failed to set {label}: {exc}", type="negative")


async def _set_input_number(
    ha: HomeAssistantClient, entity_id: str, value: float, label: str,
) -> None:
    try:
        await ha.call_service(
            "input_number",
            "set_value",
            {"entity_id": entity_id, "value": value},
        )
        ui.notify(f"{label} set to {value:.0f}", type="positive")
    except Exception as exc:
        ui.notify(f"Failed to set {label}: {exc}", type="negative")


async def _set_input_datetime(
    ha: HomeAssistantClient, entity_id: str, time_str: str, label: str,
) -> None:
    try:
        await ha.call_service(
            "input_datetime",
            "set_datetime",
            {"entity_id": entity_id, "time": time_str},
        )
        ui.notify(f"{label} set to {time_str}", type="positive")
    except Exception as exc:
        ui.notify(f"Failed to set {label}: {exc}", type="negative")
