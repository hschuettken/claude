"""Composable system prompt builder for Kairos companion agent."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from companion.intent_detector import IntentDetector

logger = logging.getLogger(__name__)

_intent_detector = IntentDetector()


def build_system_prompt(
    hot_state: dict[str, Any],
    profile: Optional[dict[str, Any]] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    date_str: Optional[str] = None,
) -> str:
    """
    Build a rich system prompt for Kairos from multiple context sources.

    Args:
        hot_state: Real-time home context from Redis (orbit, energy, training, synthesis, etc.)
        profile: User profile with persona_notes and preferences
        tools: List of available tools (tool schemas)
        date_str: Override current date (ISO format, or None for now)

    Returns:
        System prompt string for LLM injection
    """
    if profile is None:
        profile = {}
    if tools is None:
        tools = []

    # Current date/time
    if not date_str:
        now = datetime.now(timezone.utc)
        date_str = now.isoformat(timespec="seconds")
    else:
        date_str = str(date_str)

    lines = []

    # 1. Identity
    lines.append("# Kairos: Home Intelligence Companion")
    lines.append("")
    lines.append(
        "You are Kairos, Henning's AI companion for the homelab ecosystem. "
        "You have access to real-time home context (energy, calendar, tasks, infrastructure) "
        "and a suite of tools for home automation, planning, and decision support."
    )
    lines.append("")
    lines.append("**Tone**: Direct, smart, concise. No filler. Report results inline.")
    lines.append("")

    # 2. Temporal context
    lines.append("## Current Context")
    lines.append(f"**Date/Time**: {date_str}")
    lines.append("")

    # 3. Hot state summary (only include domains with data)
    if hot_state:
        lines.append("## Home State Snapshot")

        # Orbit (tasks/goals)
        orbit = hot_state.get("orbit")
        if orbit:
            task_count = orbit.get("active_count", 0)
            lines.append(f"- **Orbit**: {task_count} active tasks/goals")

        # Energy
        energy = hot_state.get("energy")
        if energy:
            solar_power = energy.get("solar_power_w", 0)
            battery_soc = energy.get("battery_soc_percent", 0)
            grid_power = energy.get("grid_power_w", 0)
            lines.append(
                f"- **Energy**: {solar_power}W solar, {battery_soc}% battery, "
                f"grid {'export' if grid_power > 0 else 'import'} {abs(grid_power)}W"
            )

        # Training
        training = hot_state.get("training")
        if training:
            last_event = training.get("last_event_summary")
            if last_event:
                lines.append(f"- **Training**: {last_event}")

        # Synthesis (recommendations)
        synthesis = hot_state.get("synthesis")
        if synthesis:
            top_rec = synthesis.get("top_recommendation")
            if top_rec:
                lines.append(f"- **Synthesis**: {top_rec}")

        # Infra alerts
        infra_alerts = hot_state.get("infra_alerts", [])
        if infra_alerts:
            alert_count = len(infra_alerts)
            lines.append(f"- **Infrastructure**: {alert_count} active alerts")

        # Calendar (upcoming events)
        calendar = hot_state.get("calendar")
        if calendar:
            next_event = calendar.get("next_event_summary")
            if next_event:
                lines.append(f"- **Calendar**: {next_event}")

        lines.append("")

    # 3b. Detected intent context (injected between home state and user profile)
    intent_section = _intent_detector.format_for_prompt(hot_state=hot_state)
    if intent_section:
        lines.append(intent_section)
        lines.append("")

    # 4. User profile
    if profile or hot_state:
        persona_notes = profile.get("persona_notes", "")
        preferences = profile.get("preferences", {})

        if persona_notes or preferences:
            lines.append("## User Profile")

            if persona_notes:
                lines.append(f"**Notes**: {persona_notes}")

            if preferences:
                pref_list = []
                for key, value in preferences.items():
                    if value:
                        pref_list.append(f"{key}: {value}")
                if pref_list:
                    lines.append("**Preferences**: " + " | ".join(pref_list))

            lines.append("")

    # 5. Available tools (service categories, not individual endpoints)
    if tools:
        # Extract unique service names from tools
        services = set()
        service_descriptions = {}

        for tool_schema in tools:
            func = tool_schema.get("function", {})
            name = func.get("name", "")
            description = func.get("description", "")

            if "__" in name:
                service_name = name.split("__")[0]
                services.add(service_name)
                if service_name not in service_descriptions:
                    service_descriptions[service_name] = description.split(" - ")[0]

        if services:
            lines.append("## Available Tools")
            for service in sorted(services):
                desc = service_descriptions.get(service, service)
                lines.append(f"- **{service}**: {desc}")
            lines.append("")

    # 6. Response guidelines
    lines.append("## Response Guidelines")
    lines.append("- Be concise unless asked to elaborate")
    lines.append("- When executing tools, report results inline (don't just confirm)")
    lines.append(
        "- For homelab operations: always confirm destructive actions with the user"
    )
    lines.append("- Use structured lists for multi-item answers")
    lines.append(
        "- If a tool requires approval and you lack user confirmation, ask explicitly"
    )
    lines.append("")

    return "\n".join(lines)


class PersonaBuilder:
    """Composable system prompt builder with stateful persona management."""

    def __init__(
        self, persona_notes: str = "", preferences: Optional[dict[str, Any]] = None
    ):
        """
        Initialize persona builder.

        Args:
            persona_notes: Initial persona notes (e.g., "likes concise responses")
            preferences: Initial preferences dict (e.g., {"timezone": "Europe/Berlin"})
        """
        self.persona_notes = persona_notes
        self.preferences = preferences or {}

    def build(
        self,
        hot_state: dict[str, Any],
        tools: Optional[list[dict[str, Any]]] = None,
        date_str: Optional[str] = None,
    ) -> str:
        """
        Build system prompt with current persona and hot state.

        Args:
            hot_state: Real-time home context
            tools: Available tools (tool schemas)
            date_str: Override current date (ISO format)

        Returns:
            System prompt string
        """
        profile = {
            "persona_notes": self.persona_notes,
            "preferences": self.preferences,
        }
        return build_system_prompt(hot_state, profile, tools, date_str)

    def update(
        self,
        persona_notes: Optional[str] = None,
        preferences: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Update persona settings.

        Args:
            persona_notes: New persona notes (replaces if provided)
            preferences: New preferences dict (merged with existing if provided)
        """
        if persona_notes is not None:
            self.persona_notes = persona_notes
            logger.info("persona_notes_updated", length=len(persona_notes))

        if preferences is not None:
            self.preferences.update(preferences)
            logger.info("preferences_updated", keys=list(preferences.keys()))
