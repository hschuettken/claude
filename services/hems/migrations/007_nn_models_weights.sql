-- HEMS schema migration 007
-- Adds weight storage columns to hems.nn_models and creates hems.nn_training_log.
-- Spec: #1033 (weights persistence), #1034 (training log)
--
-- The original hems.nn_models table (migration 003) stores metadata only.
-- This migration extends it with:
--   weights_blob     — serialized PyTorch state_dict (BYTEA)
--   model_version    — semantic version string (e.g. "1.2.0")
--   metrics          — JSON evaluation metrics snapshot
--   created_at       — already present in 003; ADD IF NOT EXISTS guard is safe

BEGIN;

-- -------------------------------------------------------------------------
-- Extend hems.nn_models with weight storage columns
-- -------------------------------------------------------------------------
ALTER TABLE hems.nn_models
    ADD COLUMN IF NOT EXISTS weights_blob   BYTEA,
    ADD COLUMN IF NOT EXISTS model_version  TEXT,
    ADD COLUMN IF NOT EXISTS metrics        JSONB;

-- Index for fast lookup of active weights by type (used by load_latest_weights)
CREATE INDEX IF NOT EXISTS idx_nn_models_type_active_created
    ON hems.nn_models (model_type, is_active, created_at DESC);

-- -------------------------------------------------------------------------
-- hems.nn_training_log — per-epoch training metrics
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.nn_training_log (
    id               BIGSERIAL    PRIMARY KEY,
    model_type       TEXT         NOT NULL,
    epoch            INTEGER      NOT NULL,
    loss             NUMERIC(12,6) NOT NULL,
    val_loss         NUMERIC(12,6),
    duration_seconds NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    samples_used     INTEGER       NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nn_training_log_model_type
    ON hems.nn_training_log (model_type, created_at DESC);

COMMIT;
