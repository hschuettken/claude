-- HEMS migration 004: PV Budget Allocator
-- Creates: hems.pv_allocation for tracking PV surplus allocation across device priorities
-- Supports Phase 3.2 PV orchestration

BEGIN;

-- -------------------------------------------------------------------------
-- hems.pv_allocation — PV surplus allocation records
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.pv_allocation (
    id                    BIGSERIAL PRIMARY KEY,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    surplus_available_kw  NUMERIC(6,2) NOT NULL,
    allocation_dict       JSONB       NOT NULL,  -- {device: allocated_kW, ...}
    battery_soc_pct       NUMERIC(5,2),          -- Battery SoC at allocation time
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pv_allocation_timestamp ON hems.pv_allocation (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pv_allocation_created_at ON hems.pv_allocation (created_at DESC);

-- -------------------------------------------------------------------------
-- hems.pv_allocation_history — Time-series log of allocation ticks
-- Lightweight log for analytics: one row per 5-min tick
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hems.pv_allocation_history (
    id                      BIGSERIAL PRIMARY KEY,
    tick_timestamp          TIMESTAMPTZ NOT NULL,
    surplus_available_kw    NUMERIC(6,2) NOT NULL,
    allocated_total_kw      NUMERIC(6,2) NOT NULL,
    remaining_kw            NUMERIC(6,2) NOT NULL,
    allocation_json         JSONB,                -- {device: {allocated_kW, priority, state}}
    cycle_number            BIGINT,               -- Control loop cycle counter
    execution_time_ms       NUMERIC(6,1),
    error_message           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pv_alloc_hist_tick ON hems.pv_allocation_history (tick_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pv_alloc_hist_created ON hems.pv_allocation_history (created_at DESC);

COMMIT;
