-- HEMS migration 005: create public.hems_* tables
-- These are the tables queried by database.py (public schema, hems_ prefix)
-- Migration 001 created hems.* schema tables which the code does NOT use.
-- Target DB: postgresql://homelab:homelab@192.168.0.80:5432/homelab

BEGIN;

-- -------------------------------------------------------------------------
-- public.hems_schedules — weekly heating schedule entries per room
-- -------------------------------------------------------------------------
-- Queried by database.py: get_current_schedule, get_schedule, list_schedules,
-- create_schedule, update_schedule
CREATE TABLE IF NOT EXISTS public.hems_schedules (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id       TEXT        NOT NULL,
    day_of_week   INTEGER     NOT NULL
                    CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Monday, 6=Sunday
    start_time    TIME        NOT NULL,
    end_time      TIME        NOT NULL,
    target_temp   NUMERIC(5,2) NOT NULL,
    mode          TEXT        NOT NULL DEFAULT 'comfort',  -- 'comfort', 'eco', 'off'
    active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hems_schedules_time_order CHECK (end_time > start_time)
);

-- Index for get_current_schedule: WHERE room_id=$1 AND day_of_week=$2 AND start_time<=$3 AND end_time>$3 AND active=true
CREATE INDEX IF NOT EXISTS idx_hems_schedules_room_dow_time
    ON public.hems_schedules (room_id, day_of_week, start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_hems_schedules_active
    ON public.hems_schedules (active);

CREATE INDEX IF NOT EXISTS idx_hems_schedules_room_id
    ON public.hems_schedules (room_id);

-- -------------------------------------------------------------------------
-- public.hems_config — key-value runtime configuration
-- -------------------------------------------------------------------------
-- Queried by database.py: get_config, set_config
CREATE TABLE IF NOT EXISTS public.hems_config (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key         TEXT        NOT NULL UNIQUE,
    value       TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for get_config: WHERE key=$1
CREATE INDEX IF NOT EXISTS idx_hems_config_key
    ON public.hems_config (key);

-- -------------------------------------------------------------------------
-- public.hems_audit_log — immutable event log for HEMS actions
-- -------------------------------------------------------------------------
-- Queried by database.py: _audit_log (INSERT only)
CREATE TABLE IF NOT EXISTS public.hems_audit_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action      TEXT        NOT NULL,
    room_id     TEXT,
    old_value   TEXT,
    new_value   TEXT,
    source      TEXT        NOT NULL DEFAULT 'api',
    details     TEXT
);

-- Indexes for common audit queries
CREATE INDEX IF NOT EXISTS idx_hems_audit_log_timestamp
    ON public.hems_audit_log (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_hems_audit_log_action
    ON public.hems_audit_log (action);

CREATE INDEX IF NOT EXISTS idx_hems_audit_log_room_id
    ON public.hems_audit_log (room_id);

COMMIT;
