-- Cognitive Layer — External Brain v2
-- Knowledge Graph (flat FK in PostgreSQL, no Neo4j / graph DB)
-- pgvector for semantic search on node embeddings

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge Graph nodes
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_nodes (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    node_type   VARCHAR(64) NOT NULL,   -- page|meeting|chat|git_commit|ha_event|calendar_event|orbit_task|orbit_goal|thought|concept
    label       VARCHAR(255) NOT NULL,
    properties  JSONB       NOT NULL DEFAULT '{}',
    embedding   vector(1536),            -- pgvector (OpenAI 1536-dim; null when not yet embedded)
    source      VARCHAR(64),             -- memora|orbit|git|ha|calendar|manual
    source_id   VARCHAR(255),            -- external ID (orbit task UUID, git SHA, HA event ID …)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS kg_nodes_type    ON kg_nodes (node_type);
CREATE INDEX IF NOT EXISTS kg_nodes_source  ON kg_nodes (source, source_id);
CREATE INDEX IF NOT EXISTS kg_nodes_created ON kg_nodes (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS kg_nodes_source_id_uq
    ON kg_nodes (source, source_id)
    WHERE source IS NOT NULL AND source_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge Graph edges (flat FK — no graph DB)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_edges (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id     UUID        NOT NULL REFERENCES kg_nodes (id) ON DELETE CASCADE,
    target_id     UUID        NOT NULL REFERENCES kg_nodes (id) ON DELETE CASCADE,
    relation_type VARCHAR(64) NOT NULL,  -- RELATES_TO|BLOCKS|DEPENDS_ON|PART_OF|CREATED_BY|DISCUSSED_IN|LEADS_TO
    weight        FLOAT       NOT NULL DEFAULT 1.0,
    properties    JSONB       NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS kg_edges_source   ON kg_edges (source_id);
CREATE INDEX IF NOT EXISTS kg_edges_target   ON kg_edges (target_id);
CREATE INDEX IF NOT EXISTS kg_edges_relation ON kg_edges (relation_type);

-- ─────────────────────────────────────────────────────────────────────────────
-- Thought Continuity Engine — unfinished thread tracking
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS thought_threads (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    title        VARCHAR(255) NOT NULL,
    summary      TEXT,
    status       VARCHAR(32) NOT NULL DEFAULT 'open',  -- open|dormant|closed
    recurrence   INT         NOT NULL DEFAULT 0,        -- times this topic has resurfaced
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    node_ids     UUID[]      NOT NULL DEFAULT '{}'      -- FK references into kg_nodes
);

CREATE INDEX IF NOT EXISTS thought_threads_status   ON thought_threads (status);
CREATE INDEX IF NOT EXISTS thought_threads_lastseen ON thought_threads (last_seen_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Cognitive Load samples (time-series of the mental-debt score)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cognitive_load_samples (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    sampled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    open_threads        INT         NOT NULL DEFAULT 0,
    overdue_tasks       INT         NOT NULL DEFAULT 0,
    unprocessed_events  INT         NOT NULL DEFAULT 0,
    debt_score          FLOAT       NOT NULL DEFAULT 0.0,  -- composite 0–100
    breakdown           JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS cognitive_load_sampled ON cognitive_load_samples (sampled_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Daily Briefing cache
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_briefings (
    id           UUID  PRIMARY KEY DEFAULT uuid_generate_v4(),
    date         DATE  NOT NULL UNIQUE,
    narrative    TEXT  NOT NULL,
    context      JSONB NOT NULL DEFAULT '{}',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Reflection reports (daily / weekly / monthly)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reflection_reports (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    period_type  VARCHAR(16) NOT NULL,  -- daily|weekly|monthly
    period_start DATE        NOT NULL,
    period_end   DATE        NOT NULL,
    content      TEXT        NOT NULL,
    metrics      JSONB       NOT NULL DEFAULT '{}',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (period_type, period_start)
);

CREATE INDEX IF NOT EXISTS reflection_period ON reflection_reports (period_type, period_start DESC);
