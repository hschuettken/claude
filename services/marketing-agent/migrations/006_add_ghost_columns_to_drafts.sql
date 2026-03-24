-- Migration 006: Add Ghost publishing columns to marketing.drafts
-- Closes Task 156 — Ghost CMS Publishing Pipeline

ALTER TABLE marketing.drafts
  ADD COLUMN IF NOT EXISTS ghost_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS ghost_url TEXT,
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_drafts_ghost_id ON marketing.drafts(ghost_id);
CREATE INDEX IF NOT EXISTS idx_drafts_published_at ON marketing.drafts(published_at);
