-- Self-Optimizing Infrastructure — schema init
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- L0 / L1 Service Health
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS soi_service_health (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name    VARCHAR(128) NOT NULL,
    monitor_level   VARCHAR(4)  NOT NULL DEFAULT 'L0',   -- L0, L1
    status          VARCHAR(32) NOT NULL DEFAULT 'unknown', -- online, offline, degraded, unknown
    last_seen       TIMESTAMPTZ,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS soi_svc_name_level_uq
    ON soi_service_health (service_name, monitor_level);

CREATE INDEX IF NOT EXISTS soi_svc_status ON soi_service_health (status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Decision Engine
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS soi_decision_rules (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(128) NOT NULL,
    description         TEXT        NOT NULL DEFAULT '',
    condition_type      VARCHAR(64) NOT NULL,
    condition_params    JSONB       NOT NULL DEFAULT '{}',
    action_type         VARCHAR(64) NOT NULL,
    action_params       JSONB       NOT NULL DEFAULT '{}',
    risk_level          VARCHAR(16) NOT NULL DEFAULT 'low',
    auto_approve        BOOLEAN     NOT NULL DEFAULT false,
    enabled             BOOLEAN     NOT NULL DEFAULT true,
    cooldown_minutes    INT         NOT NULL DEFAULT 10,
    last_fired_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS soi_rules_name_uq ON soi_decision_rules (name);
CREATE INDEX IF NOT EXISTS soi_rules_enabled ON soi_decision_rules (enabled);

CREATE TABLE IF NOT EXISTS soi_decisions (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id         UUID        REFERENCES soi_decision_rules (id) ON DELETE SET NULL,
    rule_name       VARCHAR(128) NOT NULL DEFAULT '',
    trigger_data    JSONB       NOT NULL DEFAULT '{}',
    action_type     VARCHAR(64) NOT NULL,
    action_params   JSONB       NOT NULL DEFAULT '{}',
    risk_level      VARCHAR(16) NOT NULL DEFAULT 'low',
    status          VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, approved, rejected, executing, done, failed
    auto_approved   BOOLEAN     NOT NULL DEFAULT false,
    approved_by     VARCHAR(128),
    result          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at     TIMESTAMPTZ,
    executed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS soi_decisions_status ON soi_decisions (status);
CREATE INDEX IF NOT EXISTS soi_decisions_created ON soi_decisions (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Infra Evolution Proposals
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS soi_evolution_proposals (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               VARCHAR(255) NOT NULL,
    description         TEXT        NOT NULL DEFAULT '',
    proposal_type       VARCHAR(64) NOT NULL,
    resource_target     VARCHAR(128) NOT NULL DEFAULT '',
    estimated_impact    JSONB       NOT NULL DEFAULT '{}',
    data_summary        JSONB       NOT NULL DEFAULT '{}',
    status              VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, approved, rejected, implemented
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    resolved_by         VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS soi_proposals_status ON soi_evolution_proposals (status);
CREATE INDEX IF NOT EXISTS soi_proposals_created ON soi_evolution_proposals (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Chaos Testing
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS soi_chaos_runs (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_type         VARCHAR(64) NOT NULL,
    target                  VARCHAR(128) NOT NULL,
    status                  VARCHAR(32) NOT NULL DEFAULT 'running', -- running, passed, failed, skipped
    started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    recovery_time_seconds   INT,
    result                  JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS soi_chaos_status  ON soi_chaos_runs (status);
CREATE INDEX IF NOT EXISTS soi_chaos_started ON soi_chaos_runs (started_at DESC);
