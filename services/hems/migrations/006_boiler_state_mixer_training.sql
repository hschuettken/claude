-- HEMS migration 006: boiler state log, energy allocation, NN training log, mixer PI log
-- Spec: Feature #1040 — HEMS Postgres Schema
-- Target DB: postgresql://homelab:homelab@192.168.0.80:5432/homelab
--
-- NOTE: hems.nn_models and hems.decisions already exist (migration 003).
--       hems.pv_allocation already exists (migration 004).
--       This migration adds the four remaining tables.

BEGIN;

-- -------------------------------------------------------------------------
-- hems.boiler_state — per-cycle boiler on/off state log
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.boiler_state (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    burner_on       BOOLEAN     NOT NULL,
    flow_temp       NUMERIC(5,2),                    -- Flow temperature (°C)
    return_temp     NUMERIC(5,2),                    -- Return temperature (°C)
    dhw_active      BOOLEAN     NOT NULL DEFAULT FALSE,
    mode            TEXT,                            -- 'comfort', 'eco', 'off', 'dhw'
    energy_wh       NUMERIC(10,2)                    -- Cumulative energy this cycle (Wh)
);

CREATE INDEX IF NOT EXISTS idx_boiler_state_ts
    ON hems.boiler_state (ts DESC);

-- -------------------------------------------------------------------------
-- hems.energy_allocation — per-tick PV budget allocation across consumers
-- -------------------------------------------------------------------------
-- Lightweight summary of how available PV power is allocated per tick.
-- Complements hems.pv_allocation (which stores the full allocation dict).
CREATE TABLE IF NOT EXISTS hems.energy_allocation (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pv_total_w          NUMERIC(8,2),                -- Total PV generation (W)
    house_w             NUMERIC(8,2),                -- Household base load (W)
    dhw_w               NUMERIC(8,2),                -- DHW heater allocation (W)
    ev_w                NUMERIC(8,2),                -- EV charger allocation (W)
    supplemental_w      NUMERIC(8,2),                -- Supplemental / buffer heater (W)
    grid_export_w       NUMERIC(8,2),                -- Net grid export (W)
    self_consumption_pct NUMERIC(5,2)                -- Self-consumption ratio (0–100 %)
);

CREATE INDEX IF NOT EXISTS idx_energy_allocation_ts
    ON hems.energy_allocation (ts DESC);

-- -------------------------------------------------------------------------
-- hems.nn_training_log — training run metrics per epoch
-- -------------------------------------------------------------------------
-- Appended to by model trainers; used for convergence analysis and early
-- stopping decisions.  One row per epoch per training run.
CREATE TABLE IF NOT EXISTS hems.nn_training_log (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_type          TEXT        NOT NULL,        -- 'thermal_pinn', 'demand_forecast', etc.
    epoch               INTEGER,
    loss                NUMERIC(10,6),
    val_loss            NUMERIC(10,6),
    duration_seconds    NUMERIC(8,2),
    samples_used        INTEGER,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_nn_training_log_ts
    ON hems.nn_training_log (ts DESC);

CREATE INDEX IF NOT EXISTS idx_nn_training_log_model_type
    ON hems.nn_training_log (model_type);

-- -------------------------------------------------------------------------
-- hems.mixer_control — Postgres copy of mixer PI loop data
-- -------------------------------------------------------------------------
-- Primary store is InfluxDB (hems.mixer_control measurement).
-- This table mirrors the data for SQL-based queries (e.g. oscillation analysis,
-- long-term tuning).  Written on every control tick.
CREATE TABLE IF NOT EXISTS hems.mixer_control (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    setpoint            NUMERIC(5,2),                -- Target flow temperature (°C)
    measured            NUMERIC(5,2),                -- Measured flow temperature (°C)
    error               NUMERIC(6,3),                -- setpoint − measured
    output              NUMERIC(6,3),                -- PI controller output (%)
    integral            NUMERIC(8,3),                -- Accumulated integral term
    valve_position_pct  NUMERIC(5,2),                -- Resulting valve position (0–100 %)
    action              TEXT,                        -- 'open', 'close', 'hold'
    oscillation_count   INTEGER     NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mixer_control_ts
    ON hems.mixer_control (ts DESC);

COMMIT;
