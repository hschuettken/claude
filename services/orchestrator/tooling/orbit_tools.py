"""Orbit tool definitions and handlers for Atlas orchestrator.

Provides task management, project queries, page creation, and
scheduling recommendations via NB9OS Orbit API.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from shared.log import get_logger

logger = get_logger("tooling.orbit_tools")

# NB9OS base URL and service token for Orbit API access.
NB9OS_BASE = os.environ.get("NB9OS_URL", "http://nb9os-backend:8000")
NB9OS_API_PREFIX = "/api/v1"
NB9OS_SERVICE_TOKEN = os.environ.get("NB9OS_SERVICE_TOKEN", "")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "orbit_create_task",
            "description": (
                "Create a task in Orbit project management. "
                "Requires a project_id (UUID). Priority: low/medium/high/urgent. "
                "Status defaults to 'backlog'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                    "project_id": {"type": "string", "description": "UUID of the project to add the task to"},
                    "description": {"type": "string", "description": "Task description (optional)"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Task priority (default: medium)",
                    },
                    "energy_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Energy required (default: medium)",
                    },
                    "estimated_minutes": {
                        "type": "integer",
                        "description": "Estimated time in minutes",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date in YYYY-MM-DD format (optional)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for the task (optional)",
                    },
                },
                "required": ["title", "project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_list_tasks",
            "description": (
                "List tasks from Orbit. Filter by status, project, or priority. "
                "Returns task title, status, priority, and project info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["backlog", "ready", "in_progress", "blocked", "done"],
                        "description": "Filter by task status",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Filter by project UUID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_complete_task",
            "description": "Mark an Orbit task as done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task UUID"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_list_projects",
            "description": "List Orbit projects. Filter by status (active/paused/completed/archived).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "completed", "archived"],
                        "description": "Filter by project status (default: active)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_create_page",
            "description": (
                "Create a Memora knowledge page in Orbit. "
                "Types: note, daily_note, decision_log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Page title"},
                    "content": {"type": "string", "description": "Page content as plain text"},
                    "page_type": {
                        "type": "string",
                        "enum": ["note", "daily_note", "decision_log"],
                        "description": "Page type (default: note)",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Link page to a project UUID (optional)",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_get_recommendations",
            "description": (
                "Get Orbit's 'what to do next' task recommendations. "
                "Scored by priority, deadline proximity, energy match, and time fit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "available_minutes": {
                        "type": "integer",
                        "description": "Available time in minutes (default: 60)",
                    },
                    "energy_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Current energy level",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max recommendations (default: 10)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_what_now",
            "description": (
                "Quick 'what should I do right now?' — returns top 3 task suggestions "
                "with human-friendly explanations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "available_minutes": {
                        "type": "integer",
                        "description": "Available time in minutes (default: 60)",
                    },
                    "energy_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Current energy level",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_list_lists",
            "description": (
                "Get all Orbit shared lists (shopping, todo, checklists). "
                "Returns list names, types, and item counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_get_list",
            "description": (
                "Get a specific Orbit list with all its items. "
                "Use orbit_list_lists first to find the list ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "List UUID"},
                },
                "required": ["list_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_add_list_item",
            "description": (
                "Add an item to an Orbit list. "
                "If you know the list name (e.g., 'Shopping'), "
                "call orbit_list_lists first to find the ID, then add the item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "List UUID"},
                    "content": {"type": "string", "description": "Item text to add"},
                },
                "required": ["list_id", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_check_list_item",
            "description": (
                "Check (complete) an item on an Orbit list. "
                "Use orbit_get_list to find the item ID first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "List UUID"},
                    "item_id": {"type": "string", "description": "Item UUID"},
                    "checked": {
                        "type": "boolean",
                        "description": "True to check, False to uncheck (default True)",
                    },
                },
                "required": ["list_id", "item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_create_project",
            "description": (
                "Create a new Orbit project with optional goal, milestones, and settings. "
                "Returns the created project ID and details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Project title"},
                    "description": {"type": "string", "description": "Project description (optional)"},
                    "goal": {"type": "string", "description": "Project goal or objective (optional)"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "completed", "archived"],
                        "description": "Initial project status (default: active)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Project tags (optional)",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Project due date in YYYY-MM-DD format (optional)",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "orbit_decompose_project",
            "description": (
                "Break down a project into subtasks. Analyzes the project goal and generates "
                "a list of recommended subtasks with priority and effort estimates. "
                "Can optionally auto-create the generated tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project UUID to decompose"},
                    "auto_create": {
                        "type": "boolean",
                        "description": "Whether to automatically create the generated subtasks (default: False)",
                    },
                },
                "required": ["project_id"],
            },
        },
    },
]


def _headers() -> dict[str, str]:
    """Build auth headers for NB9OS API."""
    h: dict[str, str] = {"Content-Type": "application/json"}
    if NB9OS_SERVICE_TOKEN:
        h["Authorization"] = f"Bearer {NB9OS_SERVICE_TOKEN}"
    return h


def _url(path: str) -> str:
    return f"{NB9OS_BASE}{NB9OS_API_PREFIX}/orbit{path}"


class OrbitTools:
    """Handlers for Orbit tools — all calls go through NB9OS REST API."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def orbit_create_task(
        self,
        title: str,
        project_id: str,
        description: str = "",
        priority: str = "medium",
        energy_level: str = "medium",
        estimated_minutes: Optional[int] = None,
        due_date: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create a task in Orbit."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "title": title,
            "project_id": project_id,
            "priority": priority,
            "energy_level": energy_level,
        }
        if description:
            body["description"] = description
        if estimated_minutes is not None:
            body["estimated_minutes"] = estimated_minutes
        if due_date:
            body["due_date"] = due_date
        if tags:
            body["tags"] = tags

        resp = await client.post(_url("/tasks"), json=body, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        logger.info("Created Orbit task: %s (id=%s)", title, data.get("id"))
        return data

    async def orbit_list_tasks(
        self,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List Orbit tasks with optional filters."""
        client = await self._get_client()
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if project_id:
            params["project_id"] = project_id

        resp = await client.get(_url("/tasks"), params=params, headers=_headers())
        resp.raise_for_status()
        return resp.json()

    async def orbit_complete_task(self, task_id: str) -> dict[str, Any]:
        """Mark an Orbit task as done."""
        client = await self._get_client()
        resp = await client.post(
            _url(f"/tasks/{task_id}/complete"), headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def orbit_list_projects(
        self, status: str = "active"
    ) -> dict[str, Any]:
        """List Orbit projects."""
        client = await self._get_client()
        resp = await client.get(
            _url("/projects"), params={"status": status}, headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Pages (Memora)
    # ------------------------------------------------------------------

    async def orbit_create_page(
        self,
        title: str,
        content: str = "",
        page_type: str = "note",
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a Memora knowledge page."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "title": title,
            "page_type": page_type,
        }
        if content:
            body["content_json"] = {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            }
        if project_id:
            body["project_id"] = project_id

        resp = await client.post(_url("/pages"), json=body, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        logger.info("Created Orbit page: %s (id=%s)", title, data.get("id"))
        return data

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    async def orbit_get_recommendations(
        self,
        available_minutes: int = 60,
        energy_level: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get ranked task recommendations."""
        client = await self._get_client()
        params: dict[str, Any] = {"minutes": available_minutes, "limit": limit}
        if energy_level:
            params["energy"] = energy_level

        resp = await client.get(
            _url("/recommendations"), params=params, headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def orbit_what_now(
        self,
        available_minutes: int = 60,
        energy_level: Optional[str] = None,
    ) -> dict[str, Any]:
        """Quick 'what should I do?' — top 3 suggestions."""
        client = await self._get_client()
        params: dict[str, Any] = {"minutes": available_minutes}
        if energy_level:
            params["energy"] = energy_level

        resp = await client.get(
            _url("/what-now"), params=params, headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Shared Lists
    # ------------------------------------------------------------------

    async def orbit_list_lists(self) -> dict[str, Any]:
        """Get all shared lists."""
        client = await self._get_client()
        resp = await client.get(_url("/lists"), headers=_headers())
        resp.raise_for_status()
        return resp.json()

    async def orbit_get_list(self, list_id: str) -> dict[str, Any]:
        """Get a list with all items."""
        client = await self._get_client()
        resp = await client.get(_url(f"/lists/{list_id}"), headers=_headers())
        resp.raise_for_status()
        return resp.json()

    async def orbit_add_list_item(self, list_id: str, content: str) -> dict[str, Any]:
        """Add an item to a list."""
        client = await self._get_client()
        resp = await client.post(
            _url(f"/lists/{list_id}/items"),
            json={"content": content},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("Added list item: '%s' to list %s", content, list_id)
        return data

    async def orbit_check_list_item(
        self, list_id: str, item_id: str, checked: bool = True
    ) -> dict[str, Any]:
        """Check or uncheck a list item."""
        client = await self._get_client()
        action = "check" if checked else "uncheck"
        resp = await client.post(
            _url(f"/lists/{list_id}/items/{item_id}/{action}"),
            headers=_headers(),
        )
        resp.raise_for_status()
        logger.info("%s list item %s in list %s", action, item_id, list_id)
        return resp.json()

    # ------------------------------------------------------------------
    # Project Management
    # ------------------------------------------------------------------

    async def orbit_create_project(
        self,
        title: str,
        description: str = "",
        goal: str = "",
        status: str = "active",
        tags: Optional[list[str]] = None,
        due_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new Orbit project."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "title": title,
            "status": status,
        }
        if description:
            body["description"] = description
        if goal:
            body["goal"] = goal
        if tags:
            body["tags"] = tags
        if due_date:
            body["due_date"] = due_date

        resp = await client.post(_url("/projects"), json=body, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        logger.info("Created Orbit project: %s (id=%s)", title, data.get("id"))
        return data

    async def orbit_decompose_project(
        self,
        project_id: str,
        auto_create: bool = False,
    ) -> dict[str, Any]:
        """Decompose a project into subtasks with AI assistance."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "auto_create": auto_create,
        }

        resp = await client.post(
            _url(f"/projects/{project_id}/decompose"),
            json=body,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "Decomposed project %s: generated %d subtasks",
            project_id,
            len(data.get("subtasks", [])),
        )
        return data
