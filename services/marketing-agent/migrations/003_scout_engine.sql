-- Migration 003: Scout Engine signal enhancements
-- Adds Scout-specific fields to signals table and creates supporting indexes

-- 1. Add new columns to signals table
ALTER TABLE marketing.signals
ADD COLUMN IF NOT EXISTS snippet TEXT,
ADD COLUMN IF NOT EXISTS source_domain VARCHAR(255),
ADD COLUMN IF NOT EXISTS pillar_id INTEGER,
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'new',
ADD COLUMN IF NOT EXISTS url_hash VARCHAR(64) UNIQUE,
ADD COLUMN IF NOT EXISTS search_profile_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS raw_json JSONB,
ADD COLUMN IF NOT EXISTS detected_at TIMESTAMP DEFAULT now();

-- 2. Create indexes for Scout queries
CREATE INDEX IF NOT EXISTS idx_signals_status ON marketing.signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_pillar ON marketing.signals(pillar_id);
CREATE INDEX IF NOT EXISTS idx_signals_url_hash ON marketing.signals(url_hash);
CREATE INDEX IF NOT EXISTS idx_signals_search_profile ON marketing.signals(search_profile_id);
CREATE INDEX IF NOT EXISTS idx_signals_detected_at ON marketing.signals(detected_at);

-- 3. Add foreign key constraint to content_pillars
ALTER TABLE marketing.signals
ADD CONSTRAINT fk_signals_pillar_id
FOREIGN KEY (pillar_id)
REFERENCES marketing.content_pillars(id)
ON DELETE SET NULL;

-- 4. Create status check constraint
ALTER TABLE marketing.signals
ADD CONSTRAINT check_signal_status
CHECK (status IN ('new', 'read', 'used', 'archived'));
