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

-- HenningGPT Phase 1: Decision memory RAG
CREATE TABLE IF NOT EXISTS companion.decisions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    decision    TEXT NOT NULL DEFAULT '',
    reasoning   TEXT NOT NULL DEFAULT '',
    outcome     TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    confidence  REAL NOT NULL DEFAULT 0.7,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_user_id ON companion.decisions(user_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON companion.decisions(created_at DESC);

-- HenningGPT Phase 2: Preference graph with WHY edges
CREATE TABLE IF NOT EXISTS companion.preference_graph (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          TEXT NOT NULL,
    key              TEXT NOT NULL,
    value            TEXT NOT NULL DEFAULT '',
    context          TEXT NOT NULL DEFAULT 'general',
    why              TEXT NOT NULL DEFAULT '',
    evidence         TEXT NOT NULL DEFAULT '[]',
    confidence       REAL NOT NULL DEFAULT 0.7,
    times_confirmed  INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, key, context)
);
CREATE INDEX IF NOT EXISTS idx_pref_graph_user_context ON companion.preference_graph(user_id, context);

-- HenningGPT Phase 3: Active learning — predictions
CREATE TABLE IF NOT EXISTS companion.predictions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          TEXT NOT NULL,
    session_id       TEXT NOT NULL DEFAULT '',
    context          TEXT NOT NULL DEFAULT '',
    prediction       TEXT NOT NULL DEFAULT '',
    confidence       REAL NOT NULL DEFAULT 0.7,
    category         TEXT NOT NULL DEFAULT 'general',
    feedback_correct BOOLEAN,
    feedback_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_predictions_user_id ON companion.predictions(user_id);

-- HenningGPT Phase 3: Active learning — feedback records
CREATE TABLE IF NOT EXISTS companion.prediction_feedback (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id  UUID NOT NULL REFERENCES companion.predictions(id) ON DELETE CASCADE,
    correct        BOOLEAN NOT NULL,
    correction     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pred_feedback_prediction_id ON companion.prediction_feedback(prediction_id);
"""


async def run_migrations(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
