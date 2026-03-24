-- Migration: Add search_profiles table for Scout configuration
-- Created: 2026-03-22
-- Purpose: Store configurable search profiles with scoring weights

CREATE TABLE IF NOT EXISTS marketing.search_profiles (
    id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    pillar_id INTEGER NOT NULL,
    
    -- Search configuration (arrays)
    queries TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    engines TEXT[] NOT NULL DEFAULT ARRAY['google']::TEXT[],
    
    -- Scoring weights (0.0 to 1.0, sum should be close to 1.0)
    keyword_weight FLOAT NOT NULL DEFAULT 0.35,
    authority_weight FLOAT NOT NULL DEFAULT 0.25,
    recency_weight FLOAT NOT NULL DEFAULT 0.20,
    performance_weight FLOAT NOT NULL DEFAULT 0.20,
    
    -- Scheduling
    interval_hours INTEGER NOT NULL DEFAULT 4,
    
    -- Status (1=enabled, 0=disabled)
    enabled INTEGER NOT NULL DEFAULT 1,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Indexes
    FOREIGN KEY (pillar_id) REFERENCES marketing.content_pillars(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_search_profiles_pillar_id ON marketing.search_profiles(pillar_id);
CREATE INDEX IF NOT EXISTS idx_search_profiles_enabled ON marketing.search_profiles(enabled);

-- Seed default profiles (optional - can be inserted programmatically)
-- INSERT INTO marketing.search_profiles (id, name, pillar_id, queries, engines, interval_hours)
-- VALUES
--   ('sap_datasphere', 'SAP Datasphere News', 1, ARRAY['SAP Datasphere new features 2025', 'SAP Datasphere release notes', 'SAP Business Data Cloud'], ARRAY['google', 'bing', 'duckduckgo'], 4),
--   ('sap_community', 'SAP Community Activity', 5, ARRAY['SAP Analytics Cloud site:community.sap.com', 'SAP Datasphere modeling site:community.sap.com'], ARRAY['google'], 8),
--   ('sap_release', 'SAP Release Notes', 2, ARRAY['SAP Datasphere release notes 2025', 'SAP BTP release notes Q1 2025'], ARRAY['google'], 24),
--   ('ai_enterprise', 'AI in Enterprise', 4, ARRAY['enterprise AI data architecture 2025', 'LLM enterprise integration'], ARRAY['google', 'bing'], 12),
--   ('linkedin_signals', 'LinkedIn Thought Leader Signals', 3, ARRAY['SAP data architect site:linkedin.com', 'datasphere analytics site:linkedin.com'], ARRAY['google'], 12)
-- ON CONFLICT (id) DO NOTHING;
