"""Tool registry auto-discovering from Integration Oracle + policy enforcement."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Maintains a tool catalog fetched from the Integration Oracle.

    - Fetches tools from GET /oracle/tools on startup
    - Applies policy overrides from tools_policy.yaml
    - Enforces approval gates before tool execution
    - Generates OpenAI function-calling schemas for LLM injection
    """

    def __init__(self, oracle_url: str, policy_path: Optional[str] = None):
        """
        Initialize registry.

        Args:
            oracle_url: Base URL for Integration Oracle (e.g., http://192.168.0.50:8225)
            policy_path: Path to tools_policy.yaml (optional; if None, no policy overrides)
        """
        self.oracle_url = oracle_url
        self.policy_path = policy_path
        self.tools: dict[str, dict[str, Any]] = {}
        self.policy: dict[str, Any] = {}
        self._loaded = False

    async def load(self) -> None:
        """Fetch catalog from Oracle, apply policy overrides, build registry."""
        logger.info("loading_tool_registry", oracle_url=self.oracle_url)

        # Fetch tool catalog from Oracle
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.oracle_url}/tools")
                resp.raise_for_status()
                catalog = resp.json()
        except Exception as e:
            logger.warning("oracle_tools_fetch_failed", error=str(e))
            self.tools = {}
            self._loaded = True
            return

        # Load policy overrides if provided
        if self.policy_path:
            try:
                with open(self.policy_path, "r") as f:
                    policy_yaml = yaml.safe_load(f)
                    self.policy = policy_yaml.get("tools", {})
                    logger.info("policy_loaded", path=self.policy_path)
            except Exception as e:
                logger.warning(
                    "policy_load_failed", path=self.policy_path, error=str(e)
                )
                self.policy = {}

        # Build registry from catalog
        self.tools = {}
        for tool in catalog.get("tools", []):
            name = tool.get("name")
            if not name:
                continue

            # Apply policy override or use Oracle default
            approval_default = tool.get("approval_default", "auto")
            if name in self.policy:
                policy_entry = self.policy[name]
                if isinstance(policy_entry, str):
                    approval_default = policy_entry
                elif isinstance(policy_entry, dict):
                    approval_default = policy_entry.get("default", approval_default)

            self.tools[name] = {
                "name": name,
                "display_name": tool.get("display_name", name),
                "description": tool.get("description", ""),
                "base_url": tool.get("base_url", ""),
                "category": tool.get("category", ""),
                "endpoints": tool.get("endpoints", []),
                "approval_default": approval_default,
            }

        logger.info("tool_registry_loaded", count=len(self.tools))
        self._loaded = True

    def get_tools_for_prompt(self) -> list[dict[str, Any]]:
        """
        Return list of tool schemas suitable for LLM function-calling (OpenAI format).

        Format:
        {
            "type": "function",
            "function": {
                "name": "service__endpoint",
                "description": "Service Endpoint Name - description",
                "parameters": {...}
            }
        }
        """
        tools_schema = []

        for tool_name, tool_info in self.tools.items():
            for endpoint in tool_info.get("endpoints", []):
                path = endpoint.get("path", "")
                method = endpoint.get("method", "GET")
                endpoint_desc = endpoint.get("description", "")

                # Create function name: service__endpoint_shortname
                # /search → search, /deploy/{repo}/logs → deploy_logs
                path_clean = (
                    path.lstrip("/").split("{")[0].replace("/", "_").replace("-", "_")
                )
                func_name = f"{tool_name}__{path_clean}".lower()

                full_desc = f"{tool_info['display_name']} - {endpoint_desc}"

                # Build schema with generic parameters
                schema = {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": full_desc,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "endpoint": {
                                    "type": "string",
                                    "enum": [path],
                                    "description": "API endpoint path",
                                },
                                "payload": {
                                    "type": "object",
                                    "description": "Request body/parameters",
                                },
                            },
                            "required": ["endpoint", "payload"],
                        },
                    },
                }
                tools_schema.append(schema)

        return tools_schema

    def get_tool(self, name: str) -> Optional[dict[str, Any]]:
        """Return a single tool schema by name."""
        return self.tools.get(name)

    def get_approval_level(self, tool_name: str) -> str:
        """
        Return approval level for a tool.

        Returns: 'auto', 'confirm', or 'always_confirm'
        """
        tool = self.tools.get(tool_name)
        if not tool:
            return "always_confirm"  # Safer default for unknown tools
        return tool.get("approval_default", "auto")

    async def execute(
        self,
        tool_name: str,
        endpoint: str,
        payload: dict[str, Any],
        approval_cb: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Execute a tool with approval gating.

        Args:
            tool_name: Name of the tool (e.g., 'scout', 'ops_bridge')
            endpoint: API endpoint path (e.g., '/search', '/deploy')
            payload: Request payload/parameters
            approval_cb: Optional async callable(tool_name, endpoint, payload) -> bool

        Returns:
            {"result": ..., "error": None} or {"result": None, "error": "message"}
        """
        tool = self.tools.get(tool_name)
        if not tool:
            return {"result": None, "error": f"Tool not found: {tool_name}"}

        approval_level = self.get_approval_level(tool_name)

        # Check approval gates
        if approval_level == "always_confirm":
            if not approval_cb:
                return {
                    "result": None,
                    "error": f"Tool '{tool_name}' requires explicit approval but no callback provided",
                }
            try:
                approved = await approval_cb(tool_name, endpoint, payload)
                if not approved:
                    return {
                        "result": None,
                        "error": f"Tool execution rejected by user: {tool_name}",
                    }
            except Exception as e:
                return {"result": None, "error": f"Approval callback failed: {str(e)}"}
        elif approval_level == "confirm":
            if approval_cb:
                try:
                    approved = await approval_cb(tool_name, endpoint, payload)
                    if not approved:
                        return {
                            "result": None,
                            "error": f"Tool execution rejected by user: {tool_name}",
                        }
                except Exception as e:
                    return {
                        "result": None,
                        "error": f"Approval callback failed: {str(e)}",
                    }
            # If no callback, proceed without approval (headless mode)

        # Execute the tool
        try:
            result = await self.call_oracle_tool(tool_name, endpoint, "POST", payload)
            return {"result": result, "error": None}
        except Exception as e:
            logger.error(
                "tool_execution_failed", tool=tool_name, endpoint=endpoint, error=str(e)
            )
            return {"result": None, "error": str(e)}

    async def call_oracle_tool(
        self,
        tool_name: str,
        endpoint_path: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Make HTTP call to the service via Oracle or direct to base_url.

        Args:
            tool_name: Name of the tool
            endpoint_path: API endpoint path (e.g., '/search')
            method: HTTP method (GET, POST, etc.)
            payload: Request body or parameters

        Returns:
            Response JSON from the service
        """
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        base_url = tool.get("base_url", "")
        if not base_url:
            raise ValueError(f"Tool '{tool_name}' has no base_url")

        url = f"{base_url}{endpoint_path}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, params=payload)
                elif method.upper() == "POST":
                    resp = await client.post(url, json=payload)
                elif method.upper() == "PUT":
                    resp = await client.put(url, json=payload)
                elif method.upper() == "DELETE":
                    resp = await client.delete(url, json=payload)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            logger.error("http_call_failed", url=url, method=method, error=str(e))
            raise
        except Exception as e:
            logger.error(
                "tool_call_failed", tool=tool_name, endpoint=endpoint_path, error=str(e)
            )
            raise
