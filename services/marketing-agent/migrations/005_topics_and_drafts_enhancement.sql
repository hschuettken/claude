-- Migration 005: Enhanced topics and drafts tables for full Task 129 support
-- Adds missing columns and constraints for topic scoring and draft generation

-- Ensure tables exist with all required columns
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS score NUMERIC(4,3) DEFAULT 0;
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS score_breakdown JSONB DEFAULT NULL;
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS signal_ids INTEGER[] DEFAULT '{}';
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS pillar_id INTEGER DEFAULT NULL;
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'candidate';
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT NULL;
ALTER TABLE marketing.topics ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_topics_score ON marketing.topics(score DESC);
CREATE INDEX IF NOT EXISTS idx_topics_status ON marketing.topics(status);
CREATE INDEX IF NOT EXISTS idx_topics_pillar_id ON marketing.topics(pillar_id);
CREATE INDEX IF NOT EXISTS idx_topics_updated_at ON marketing.topics(updated_at);

-- Enhance drafts table
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS format VARCHAR(32) DEFAULT 'blog';
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS outline JSONB DEFAULT NULL;
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]';
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS seo_meta JSONB DEFAULT NULL;
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS visual_prompt TEXT DEFAULT NULL;
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS confidence_labels JSONB DEFAULT '{}';
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS risk_flags JSONB DEFAULT '[]';
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS word_count INTEGER DEFAULT 0;
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS generated_by VARCHAR(128) DEFAULT 'draft-writer-v1';
ALTER TABLE marketing.drafts ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Add indexes for drafts
CREATE INDEX IF NOT EXISTS idx_drafts_format ON marketing.drafts(format);
CREATE INDEX IF NOT EXISTS idx_drafts_generated_at ON marketing.drafts(generated_at);
CREATE INDEX IF NOT EXISTS idx_drafts_word_count ON marketing.drafts(word_count);

-- Add content_pillars seed data if not exists
INSERT INTO marketing.content_pillars (name, description, color, target_audience) VALUES
    ('SAP Deep Technical', 'SAP Datasphere, semantic modeling, BTP architecture', '#0066CC', 'Enterprise Data Engineers'),
    ('SAP Roadmap & Release', 'SAP product releases, announcements, forecasts', '#0099FF', 'Enterprise Technical Leaders'),
    ('Architecture & Data Design', 'System design patterns, data modeling best practices', '#CC0099', 'Enterprise Architects'),
    ('AI in Enterprise', 'LLM integration, AI governance, enterprise AI patterns', '#FF6600', 'Enterprise Innovation Teams'),
    ('Builder Stories & Lab', 'Personal projects, Henning''s lab, hands-on exploration', '#FF0099', 'Technical Practitioners'),
    ('Personal & Insights', 'Personal thoughts, industry perspectives, career', '#9900CC', 'Industry Peers')
ON CONFLICT (name) DO NOTHING;

-- Add default voice rules if not exists
INSERT INTO marketing.voice_rules (rule_type, content) VALUES
    ('never_say', 'generic AI buzzwords without specifics'),
    ('never_say', 'client names or confidential details'),
    ('never_say', 'unverified product roadmap claims'),
    ('always_say', 'concrete technical examples'),
    ('always_say', 'personal perspective or opinion'),
    ('always_say', 'sources and citations')
ON CONFLICT DO NOTHING;
