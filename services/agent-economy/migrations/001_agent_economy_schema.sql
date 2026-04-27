-- Agent Economy — Autonomous Agent Economy
-- Agent registry, task broker, budget tracking, reputation scoring, spawn approval

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- Agent Registry
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ae_agents (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(128) NOT NULL,
    agent_type          VARCHAR(64) NOT NULL,   -- main|architect|dev|qa|devops|team-lead|backlog-agent|spec-retro|custom
    capabilities        TEXT[]      NOT NULL DEFAULT '{}',  -- task types this agent can handle
    description         TEXT,
    status              VARCHAR(32) NOT NULL DEFAULT 'active',  -- active|inactive|busy
    spawned_by          UUID        REFERENCES ae_agents (id) ON DELETE SET NULL,
    ttl_seconds         INT,                   -- non-null for self-spawned agents
    expires_at          TIMESTAMPTZ,           -- computed from ttl_seconds at spawn time
    budget_tokens_total INT         NOT NULL DEFAULT 0,  -- 0 = unlimited
    budget_tokens_used  INT         NOT NULL DEFAULT 0,
    reputation_score    FLOAT       NOT NULL DEFAULT 1.0, -- 0.0–1.0
    tasks_completed     INT         NOT NULL DEFAULT 0,
    tasks_failed        INT         NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ae_agents_name_uq ON ae_agents (name);
CREATE INDEX IF NOT EXISTS ae_agents_type   ON ae_agents (agent_type);
CREATE INDEX IF NOT EXISTS ae_agents_status ON ae_agents (status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Task Broker
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ae_tasks (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    task_type           VARCHAR(64) NOT NULL,   -- capability required to handle this task
    status              VARCHAR(32) NOT NULL DEFAULT 'created',  -- created|claimed|completed|failed
    priority            INT         NOT NULL DEFAULT 3,  -- 1=lowest, 5=highest
    assigned_to         UUID        REFERENCES ae_agents (id) ON DELETE SET NULL,
    created_by          UUID        REFERENCES ae_agents (id) ON DELETE SET NULL,
    nats_subject        VARCHAR(255),           -- originating NATS topic (if event-driven)
    nats_payload        JSONB       NOT NULL DEFAULT '{}',
    budget_tokens_max   INT         NOT NULL DEFAULT 10000,
    tokens_used         INT         NOT NULL DEFAULT 0,
    quality_score       FLOAT,                 -- set on completion (0.0–1.0)
    result              JSONB,
    error               TEXT,
    claimed_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ae_tasks_status      ON ae_tasks (status);
CREATE INDEX IF NOT EXISTS ae_tasks_type        ON ae_tasks (task_type);
CREATE INDEX IF NOT EXISTS ae_tasks_assigned_to ON ae_tasks (assigned_to);
CREATE INDEX IF NOT EXISTS ae_tasks_priority    ON ae_tasks (priority DESC, created_at ASC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Budget Log — token spend per agent/task
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ae_budget_log (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID        NOT NULL REFERENCES ae_agents (id) ON DELETE CASCADE,
    task_id     UUID        REFERENCES ae_tasks (id) ON DELETE SET NULL,
    tokens_used INT         NOT NULL,
    model_name  VARCHAR(128),
    operation   VARCHAR(128),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ae_budget_log_agent   ON ae_budget_log (agent_id);
CREATE INDEX IF NOT EXISTS ae_budget_log_task    ON ae_budget_log (task_id);
CREATE INDEX IF NOT EXISTS ae_budget_log_created ON ae_budget_log (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Audit Log — Bifrost API gateway audit trail
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ae_audit_log (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id     UUID        REFERENCES ae_agents (id) ON DELETE SET NULL,
    agent_name   VARCHAR(128),
    method       VARCHAR(16)  NOT NULL,
    path         VARCHAR(512) NOT NULL,
    status_code  INT,
    ip_address   VARCHAR(64),
    request_body JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ae_audit_log_agent   ON ae_audit_log (agent_id);
CREATE INDEX IF NOT EXISTS ae_audit_log_created ON ae_audit_log (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Spawn Requests — self-spawning approval workflow
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ae_spawn_requests (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    requested_by     UUID        NOT NULL REFERENCES ae_agents (id) ON DELETE CASCADE,
    template_name    VARCHAR(128) NOT NULL,  -- agent type template to spawn
    purpose          TEXT        NOT NULL,
    capabilities     TEXT[]      NOT NULL DEFAULT '{}',
    ttl_seconds      INT,
    status           VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|cancelled
    approved_by      VARCHAR(128),           -- agent name or "system" (auto-approved)
    spawned_agent_id UUID        REFERENCES ae_agents (id) ON DELETE SET NULL,
    rejection_reason TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ae_spawn_requests_status ON ae_spawn_requests (status);
CREATE INDEX IF NOT EXISTS ae_spawn_requests_requester ON ae_spawn_requests (requested_by);
