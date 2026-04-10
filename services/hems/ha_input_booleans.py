"""Home Assistant input_booleans for HEMS control modes.

Creates input_boolean helpers in Home Assistant for controlling HEMS modes:
- eco_mode: Energy-efficient mode
- comfort_mode: User comfort prioritized
- away_mode: House is unoccupied
- boost_mode: Maximum heating
- fallback_mode: Fallback when heartbeat is lost
- dry_run: Test mode without actual control actions

Usage:
    from ha_input_booleans import InputBooleanProvisioner
    from config import HEMSSettings

    settings = HEMSSettings()
    provisioner = InputBooleanProvisioner(ha_url=settings.ha_url, ha_token=settings.hems_ha_token)

    await provisioner.provision_input_booleans()
    states = await provisioner.get_mode_states()
    print(states)  # {"eco_mode": True, "comfort_mode": False, ...}
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("hems.ha_input_booleans")

# HEMS input_boolean definitions: modes and control states
HEMS_INPUT_BOOLEANS = {
    "hems_eco_mode": {
        "name": "HEMS Eco Mode",
        "icon": "mdi:leaf",
        "initial": False,
    },
    "hems_comfort_mode": {
        "name": "HEMS Comfort Mode",
        "icon": "mdi:sofa",
        "initial": False,
    },
    "hems_away_mode": {
        "name": "HEMS Away Mode",
        "icon": "mdi:home-export-outline",
        "initial": False,
    },
    "hems_boost_mode": {
        "name": "HEMS Boost Mode",
        "icon": "mdi:fire",
        "initial": False,
    },
    "hems_fallback_mode": {
        "name": "HEMS Fallback Mode",
        "icon": "mdi:alert",
        "initial": False,
    },
    "hems_dry_run": {
        "name": "HEMS Dry Run",
        "icon": "mdi:test-tube",
        "initial": False,
    },
}


class InputBooleanProvisioner:
    """Provisions HEMS control mode input_booleans in Home Assistant."""

    def __init__(self, ha_url: str, ha_token: str) -> None:
        """Initialize provisioner with HA connection details.

        Args:
            ha_url: Base URL for HA (e.g., "http://192.168.0.40:8123")
            ha_token: HA long-lived access token
        """
        self.ha_url = ha_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def provision_input_booleans(self) -> dict[str, bool]:
        """Create HEMS input_boolean helpers in Home Assistant.

        Attempts to create via HA REST service API. If that fails (e.g., HA 2022 or earlier),
        logs a warning with YAML snippet for manual configuration.

        Returns:
            Dict mapping entity_id -> creation_success (bool)
        """
        results: dict[str, bool] = {}
        client = await self._get_client()

        for entity_id, config in HEMS_INPUT_BOOLEANS.items():
            try:
                # Try the HA config create endpoint (HA 2023+)
                # This is a common pattern but may return 501 Not Implemented
                resp = await client.post(
                    f"{self.ha_url}/api/config/input_boolean/config",
                    json={
                        "name": config["name"],
                        "icon": config["icon"],
                        "unique_id": entity_id,
                    },
                )
                if resp.status_code in (200, 201):
                    results[entity_id] = True
                    logger.info(
                        "input_boolean_created",
                        entity_id=entity_id,
                        name=config["name"],
                    )
                elif resp.status_code == 501:
                    # Not Implemented — fall back to YAML generation
                    logger.warning(
                        "input_boolean_not_supported",
                        entity_id=entity_id,
                        hint="HA version may not support REST config API. Use YAML configuration.",
                    )
                    results[entity_id] = False
                else:
                    logger.warning(
                        "input_boolean_creation_failed",
                        entity_id=entity_id,
                        status_code=resp.status_code,
                    )
                    results[entity_id] = False
            except httpx.HTTPError as exc:
                logger.exception(
                    "input_boolean_create_error",
                    entity_id=entity_id,
                    error=str(exc),
                )
                results[entity_id] = False

        # Generate YAML snippet for manual configuration
        self._generate_yaml_snippet()

        return results

    def _generate_yaml_snippet(self) -> None:
        """Generate and log YAML configuration snippet for manual addition to configuration.yaml.

        This is useful when the REST API doesn't support direct creation.
        """
        yaml_lines = ["# Add to configuration.yaml:", "input_boolean:"]
        for entity_id, config in HEMS_INPUT_BOOLEANS.items():
            # Convert entity_id from "hems_eco_mode" to "eco_mode" for YAML key
            yaml_key = entity_id.replace("hems_", "")
            yaml_lines.append(f"  {yaml_key}:")
            yaml_lines.append(f'    name: "{config["name"]}"')
            yaml_lines.append(f"    icon: {config['icon']}")
            yaml_lines.append(f"    initial: {str(config['initial']).lower()}")

        yaml_snippet = "\n".join(yaml_lines)
        logger.info("yaml_configuration_snippet", snippet=yaml_snippet)

    async def get_mode_states(self) -> dict[str, bool]:
        """Get current state of all HEMS mode input_booleans.

        Fetches all entity states and filters to HEMS input_boolean entities.

        Returns:
            Dict mapping mode name (without "hems_" prefix) -> boolean state
            Example: {"eco_mode": True, "comfort_mode": False, ...}
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.ha_url}/api/states")
            resp.raise_for_status()
            states = resp.json()

            mode_states: dict[str, bool] = {}
            for state_obj in states:
                entity_id = state_obj.get("entity_id", "")
                if entity_id.startswith("input_boolean.hems_"):
                    mode_name = entity_id.replace("input_boolean.hems_", "")
                    is_on = state_obj.get("state") == "on"
                    mode_states[mode_name] = is_on

            logger.info("mode_states_fetched", modes=list(mode_states.keys()))
            return mode_states
        except httpx.HTTPError as exc:
            logger.exception("get_mode_states_failed", error=str(exc))
            return {}
