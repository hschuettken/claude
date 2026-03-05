"""Infer task type from request context."""

from __future__ import annotations

import re

from .models import TaskType
from .config import Settings


TASK_PREFIXES = {t.value: t for t in TaskType}

# Simple keyword heuristics for auto-classification
CODE_KEYWORDS = re.compile(
    r"\b(function|def |class |import |const |var |let |return |async |await |```"
    r"|write code|implement|refactor|debug|fix the bug|programming)\b",
    re.IGNORECASE,
)
REASONING_KEYWORDS = re.compile(
    r"\b(step by step|think carefully|reason|analyze|prove|logic|mathematical"
    r"|chain of thought|let'?s think)\b",
    re.IGNORECASE,
)


def classify_request(
    model: str,
    prompt: str = "",
    header_task: str | None = None,
    settings: Settings | None = None,
) -> tuple[TaskType | None, str]:
    """Return (task_type, resolved_model).

    If model has a task prefix (e.g. ``fast/anything``), strip it and return
    the task type plus the resolved model name from config.
    """
    # 1. Check model name prefix
    for prefix, task in TASK_PREFIXES.items():
        if model.startswith(f"{prefix}/"):
            resolved = _resolve_model(task, settings)
            return task, resolved or model[len(prefix) + 1:]

    # 2. X-Task-Type header
    if header_task and header_task.lower() in TASK_PREFIXES:
        task = TASK_PREFIXES[header_task.lower()]
        resolved = _resolve_model(task, settings)
        return task, resolved or model

    # 3. Auto-inference (lightweight)
    if prompt:
        if CODE_KEYWORDS.search(prompt):
            return TaskType.CODE, _resolve_model(TaskType.CODE, settings) or model
        if REASONING_KEYWORDS.search(prompt):
            return TaskType.REASONING, _resolve_model(TaskType.REASONING, settings) or model

    return None, model


def _resolve_model(task: TaskType, settings: Settings | None) -> str | None:
    """Pick the first model in the task's preference list."""
    if not settings:
        return None
    prefs = settings.routing.task_model_map.get(task.value, [])
    return prefs[0] if prefs else None
