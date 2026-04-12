"""Pydantic models for companion DB rows (no ORM)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CompanionSession(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompanionMessage(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    role: str  # user | assistant | tool
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    token_count: int = 0


class CompanionUserProfile(BaseModel):
    user_id: str
    persona_notes: str = ""
    preferences: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class CompanionDispatch(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID | None = None
    prompt: str | None = None  # prompt_excerpt stored in DB
    branch: str | None = None
    worktree_path: str | None = None
    status: str = "pending"  # pending | running | success | failed | cancelled
    pr_url: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    token_used: int = 0
