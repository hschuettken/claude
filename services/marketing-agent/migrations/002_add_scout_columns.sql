-- Marketing Agent Migration: Add Scout Engine Columns
-- Adds new columns to signals table for Scout Engine functionality
-- Date: 2026-03-22

BEGIN;

-- Add new columns to signals table
ALTER TABLE marketing.signals
    ADD COLUMN url_hash VARCHAR(64) UNIQUE,
    ADD COLUMN source_domain VARCHAR(255),
    ADD COLUMN snippet TEXT,
    ADD COLUMN pillar_id INTEGER,
    ADD COLUMN search_profile_id VARCHAR(128),
    ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'new',
    ADD COLUMN raw_json TEXT,
    ADD COLUMN detected_at TIMESTAMP;

-- Create indexes for new columns
CREATE INDEX idx_signals_url_hash ON marketing.signals(url_hash);
CREATE INDEX idx_signals_source_domain ON marketing.signals(source_domain);
CREATE INDEX idx_signals_pillar_id ON marketing.signals(pillar_id);
CREATE INDEX idx_signals_search_profile_id ON marketing.signals(search_profile_id);
CREATE INDEX idx_signals_status ON marketing.signals(status);
CREATE INDEX idx_signals_detected_at ON marketing.signals(detected_at);

-- Update created_at index to include it for time-based queries
CREATE INDEX idx_signals_created_at_desc ON marketing.signals(created_at DESC);

COMMIT;
