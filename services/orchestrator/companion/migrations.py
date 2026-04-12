"""One-shot schema creation for companion tables."""

from __future__ import annotations

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS companion;

CREATE TABLE IF NOT EXISTS companion.sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT NOT NULL,
    title       TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS companion.messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES companion.sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
    content     TEXT NOT NULL DEFAULT '',
    tool_calls  JSONB DEFAULT '[]',
    token_count INT DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON companion.messages(session_id);

CREATE TABLE IF NOT EXISTS companion.user_profiles (
    user_id       TEXT PRIMARY KEY,
    persona_notes TEXT DEFAULT '',
    preferences   JSONB DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS companion.dispatches (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID REFERENCES companion.sessions(id),
    prompt_excerpt TEXT,
    branch         TEXT,
    worktree_path  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','success','failed','cancelled')),
    pr_url         TEXT,
    token_used     INT DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ
);
"""


async def run_migrations(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
