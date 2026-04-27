"""Ingest Orbit task/goal completions → KG nodes.

Polls the nb9os Orbit API for recently completed tasks and goals,
maps them to `orbit_task` / `orbit_goal` nodes, and creates
PART_OF edges from tasks to their parent goals/projects.

Creates:
  - `orbit_task` node per completed task
  - `orbit_goal` node per goal
  - PART_OF edges: task → goal / project
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings
from .. import knowledge_graph as kg
from ..models import EdgeCreate, IngestResult, NodeCreate

logger = logging.getLogger(__name__)


async def ingest_orbit(days: int = 7) -> IngestResult:
    """Fetch Orbit completions from the last `days` days and create KG nodes."""
    result = IngestResult(source="orbit", nodes_created=0, edges_created=0)
    try:
        tasks = await _fetch_completed_tasks(days)
        goals = await _fetch_goals()
    except Exception as exc:
        result.errors.append(f"Orbit API fetch failed: {exc}")
        return result

    # Build goal-id → node map
    goal_nodes: dict[str, Any] = {}
    for goal in goals:
        gid = str(goal.get("id") or "")
        node = await kg.create_node(NodeCreate(
            node_type="orbit_goal",
            label=goal.get("title") or goal.get("name") or "Unnamed goal",
            properties={
                "status": goal.get("status", ""),
                "area": goal.get("life_area") or goal.get("area", ""),
                "target_date": goal.get("target_date") or goal.get("due_date", ""),
                "progress": goal.get("progress", 0),
            },
            source="orbit",
            source_id=f"goal:{gid}",
        ))
        if node:
            result.nodes_created += 1
            goal_nodes[gid] = node

    for task in tasks:
        tid = str(task.get("id") or "")
        task_node = await kg.create_node(NodeCreate(
            node_type="orbit_task",
            label=task.get("title") or task.get("name") or "Unnamed task",
            properties={
                "status": task.get("status", "completed"),
                "completed_at": task.get("completed_at") or task.get("updated_at", ""),
                "project": task.get("project") or task.get("project_name", ""),
                "tags": task.get("tags", []),
                "effort": task.get("effort") or task.get("estimated_minutes", 0),
            },
            source="orbit",
            source_id=f"task:{tid}",
        ))
        if task_node:
            result.nodes_created += 1

        # Link task → goal if present
        goal_id = str(task.get("goal_id") or task.get("parent_goal_id") or "")
        if goal_id and goal_id in goal_nodes:
            edge = await kg.create_edge(EdgeCreate(
                source_id=task_node.id,
                target_id=goal_nodes[goal_id].id,
                relation_type="PART_OF",
            ))
            if edge:
                result.edges_created += 1

    logger.info(
        "orbit_ingested tasks=%d goals=%d edges=%d errors=%d",
        len(tasks), len(goals), result.edges_created, len(result.errors),
    )
    return result


async def _fetch_completed_tasks(days: int) -> list[dict[str, Any]]:
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.orbit_url}/api/orbit/tasks",
            params={"status": "completed", "since": since, "limit": 200},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("tasks", [])


async def _fetch_goals() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.orbit_url}/api/orbit/goals",
            params={"limit": 100},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("goals", [])
