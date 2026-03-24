-- HEMS schema migration 003
-- Creates: hems.thermal_params, hems.nn_models, hems.decisions, hems.mode_history, hems.profiles
-- Target DB: postgresql://homelab:homelab@192.168.0.80:5432/homelab
-- Spec: atlas/reports/spec-retro-hems-2026-03-22.md §8 PostgreSQL Schema

BEGIN;

-- -------------------------------------------------------------------------
-- hems.thermal_params — Room-level thermal properties for physics model
-- -------------------------------------------------------------------------
-- Stores R (resistance) and C (capacitance) parameters calibrated per room.
-- Used by thermal_model.py:PhysicsModel for temperature prediction.
CREATE TABLE IF NOT EXISTS hems.thermal_params (
    id              BIGSERIAL PRIMARY KEY,
    room_id         TEXT        NOT NULL UNIQUE,        -- e.g. 'living_room', 'bedroom_1'
    r_value         NUMERIC(10,4) NOT NULL,             -- Thermal resistance (K/W)
    c_value         NUMERIC(10,4) NOT NULL,             -- Thermal capacitance (J/K)
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence      NUMERIC(5,2) NOT NULL DEFAULT 0.0
                    CHECK (confidence BETWEEN 0.0 AND 100.0), -- Calibration confidence (0–100%)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_thermal_params_room_id
    ON hems.thermal_params (room_id);

-- -------------------------------------------------------------------------
-- hems.nn_models — Neural Network model registry and metadata
-- -------------------------------------------------------------------------
-- Tracks trained PINN/LSTM models: versions, performance, deployment status.
CREATE TABLE IF NOT EXISTS hems.nn_models (
    id              BIGSERIAL PRIMARY KEY,
    model_id        TEXT        NOT NULL UNIQUE,        -- e.g. 'thermal_lstm_v1', 'pinn_thermal_v2'
    model_type      TEXT        NOT NULL,               -- 'lstm', 'pinn', 'ensemble'
    version         TEXT        NOT NULL,               -- Semantic version (e.g. '1.0.0')
    trained_at      TIMESTAMPTZ NOT NULL,               -- Training completion timestamp
    mae_score       NUMERIC(8,4),                       -- Mean Absolute Error on validation set
    filepath        TEXT,                               -- S3 or local path to model checkpoint
    is_active       BOOLEAN     NOT NULL DEFAULT FALSE, -- Currently deployed/used for inference
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT                                -- Training notes, hyperparams, etc.
);

CREATE INDEX IF NOT EXISTS idx_nn_models_model_id
    ON hems.nn_models (model_id);

CREATE INDEX IF NOT EXISTS idx_nn_models_is_active
    ON hems.nn_models (is_active);

CREATE INDEX IF NOT EXISTS idx_nn_models_trained_at
    ON hems.nn_models (trained_at DESC);

-- -------------------------------------------------------------------------
-- hems.decisions — Control decisions made by the thermal model/policy
-- -------------------------------------------------------------------------
-- Immutable log of HEMS decisions: mode changes, setpoint overrides, reasoning.
CREATE TABLE IF NOT EXISTS hems.decisions (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode            TEXT        NOT NULL,               -- 'comfort', 'eco', 'off', 'dhw'
    flow_temp_setpoint NUMERIC(5,2) NOT NULL,          -- Setpoint sent to mixer (°C)
    reason          TEXT,                               -- Explanation: 'schedule', 'pv_available', 'cost_optimization', 'manual_override', etc.
    pv_available_w  NUMERIC(10,1),                      -- Available PV power at decision time (W)
    outdoor_temp_c  NUMERIC(5,2),                       -- Ambient temperature (°C)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_timestamp
    ON hems.decisions (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_decisions_mode
    ON hems.decisions (mode);

CREATE INDEX IF NOT EXISTS idx_decisions_reason
    ON hems.decisions (reason);

-- -------------------------------------------------------------------------
-- hems.mode_history — State machine transitions (mode changes)
-- -------------------------------------------------------------------------
-- Tracks when and why HEMS switched modes (comfort ↔ eco ↔ off).
CREATE TABLE IF NOT EXISTS hems.mode_history (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode            TEXT        NOT NULL,               -- New mode: 'comfort', 'eco', 'off', 'dhw'
    trigger         TEXT        NOT NULL,               -- Reason for transition: 'schedule', 'manual', 'cost_optimization', 'emergency', 'pv_available'
    duration_minutes BIGINT,                            -- How long this mode stayed active (calculated from next entry) (minutes)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mode_history_timestamp
    ON hems.mode_history (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_mode_history_mode
    ON hems.mode_history (mode);

CREATE INDEX IF NOT EXISTS idx_mode_history_trigger
    ON hems.mode_history (trigger);

-- -------------------------------------------------------------------------
-- hems.profiles — User comfort profiles and schedules
-- -------------------------------------------------------------------------
-- Stores named temperature profiles with per-hour target temps and occupancy patterns.
-- Referenced by adaptive_schedule.py during Phase 4 schedule generation.
CREATE TABLE IF NOT EXISTS hems.profiles (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,        -- e.g. 'weekday_comfort', 'weekend_eco', 'guest_mode'
    temp_setpoints  JSONB       NOT NULL,               -- Hour-by-hour setpoints: {"0": 16.0, "1": 16.0, ..., "23": 21.0}
    active_hours    JSONB       NOT NULL,               -- Occupancy pattern per hour: {"0": false, "1": false, ..., "8": true, ...}
    is_default      BOOLEAN     NOT NULL DEFAULT FALSE, -- Default profile when no override
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_name
    ON hems.profiles (name);

CREATE INDEX IF NOT EXISTS idx_profiles_is_default
    ON hems.profiles (is_default);

COMMIT;
