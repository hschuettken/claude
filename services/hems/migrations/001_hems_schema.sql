-- HEMS schema migration 001
-- Creates: hems.schedules, hems.config, hems.audit_log
-- Target DB: postgresql://homelab:homelab@192.168.0.80:5432/homelab

BEGIN;

-- -------------------------------------------------------------------------
-- Schema
-- -------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS hems;

-- -------------------------------------------------------------------------
-- hems.schedules — energy dispatch schedule entries
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.schedules (
    id            BIGSERIAL PRIMARY KEY,
    device        TEXT        NOT NULL,                  -- e.g. 'ev_charger', 'boiler'
    start_time    TIMESTAMPTZ NOT NULL,
    end_time      TIMESTAMPTZ NOT NULL,
    power_kw      NUMERIC(8,3) NOT NULL,
    priority      SMALLINT    NOT NULL DEFAULT 5
                    CHECK (priority BETWEEN 1 AND 10),
    notes         TEXT,
    created_by    TEXT        NOT NULL DEFAULT 'api',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT schedules_time_order CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_schedules_start_time  ON hems.schedules (start_time);
CREATE INDEX IF NOT EXISTS idx_schedules_device       ON hems.schedules (device);
CREATE INDEX IF NOT EXISTS idx_schedules_is_active    ON hems.schedules (is_active);

-- -------------------------------------------------------------------------
-- hems.config — key-value runtime configuration
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.config (
    key         TEXT PRIMARY KEY,
    value       TEXT        NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT        NOT NULL DEFAULT 'system'
);

-- Seed default config values
INSERT INTO hems.config (key, value, description) VALUES
    ('HEMS_MODE',             'auto',                       'Operating mode: auto | manual | off'),
    ('HEMS_ORCHESTRATOR_URL', 'http://orchestrator:8000',   'Internal orchestrator base URL'),
    ('HEMS_HA_TOKEN',         '',                           'Home Assistant long-lived access token'),
    ('HEMS_DB_URL',           'postgresql://homelab:homelab@192.168.0.80:5432/homelab', 'PostgreSQL connection string')
ON CONFLICT (key) DO NOTHING;

-- -------------------------------------------------------------------------
-- hems.audit_log — immutable event log
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       TEXT        NOT NULL DEFAULT 'system',  -- 'api', 'scheduler', 'ha', etc.
    action      TEXT        NOT NULL,                   -- e.g. 'mode_change', 'schedule_create'
    entity_type TEXT,                                   -- e.g. 'schedule', 'config'
    entity_id   TEXT,
    old_value   JSONB,
    new_value   JSONB,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts          ON hems.audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor       ON hems.audit_log (actor);
CREATE INDEX IF NOT EXISTS idx_audit_log_action      ON hems.audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity_type ON hems.audit_log (entity_type);

COMMIT;
