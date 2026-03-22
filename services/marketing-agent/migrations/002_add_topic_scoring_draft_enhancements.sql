-- Marketing Agent Schema Migration
-- Adds Topic Scoring Engine + Draft Writer enhancements
-- Round 20 | Task 129

-- 1. ALTER marketing.topics table to add new columns for scoring
ALTER TABLE marketing.topics 
ADD COLUMN IF NOT EXISTS score NUMERIC(4,3) DEFAULT 0,
ADD COLUMN IF NOT EXISTS score_breakdown JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS signal_ids INTEGER[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS pillar_id INTEGER DEFAULT NULL,
ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'candidate',
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Add index on score and status for efficient querying
CREATE INDEX IF NOT EXISTS idx_topics_score ON marketing.topics(score DESC);
CREATE INDEX IF NOT EXISTS idx_topics_status ON marketing.topics(status);
CREATE INDEX IF NOT EXISTS idx_topics_pillar_id ON marketing.topics(pillar_id);
CREATE INDEX IF NOT EXISTS idx_topics_updated_at ON marketing.topics(updated_at DESC);

-- 2. ALTER marketing.drafts table to add new columns for enhanced metadata
ALTER TABLE marketing.drafts
ADD COLUMN IF NOT EXISTS outline JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS seo_meta JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS visual_prompt TEXT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS confidence_labels JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS risk_flags JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS word_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS format VARCHAR(32) DEFAULT 'blog';

-- Add index for word_count and format
CREATE INDEX IF NOT EXISTS idx_drafts_word_count ON marketing.drafts(word_count);
CREATE INDEX IF NOT EXISTS idx_drafts_format ON marketing.drafts(format);

-- Update platforms to use format field (backward compatible)
UPDATE marketing.drafts SET format = platform WHERE format = 'blog';
