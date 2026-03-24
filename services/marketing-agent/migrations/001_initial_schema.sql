-- Migration 001: Marketing Agent — Full 8-table schema
-- Creates all tables for marketing signals, drafts, and publishing

CREATE SCHEMA IF NOT EXISTS marketing;

-- 1. Marketing signals/opportunities
CREATE TABLE IF NOT EXISTS marketing.signals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(1024),
    source VARCHAR(100) NOT NULL,  -- scout, manual, research, etc.
    relevance_score DECIMAL(3,2) DEFAULT 0.5,  -- 0.00-1.00
    kg_node_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_relevance CHECK (relevance_score >= 0 AND relevance_score <= 1)
);

CREATE INDEX idx_signals_created_at ON marketing.signals(created_at DESC);
CREATE INDEX idx_signals_relevance ON marketing.signals(relevance_score DESC);
CREATE INDEX idx_signals_kg_node ON marketing.signals(kg_node_id);
CREATE INDEX idx_signals_source ON marketing.signals(source);

-- 2. Content topics/pillars
CREATE TABLE IF NOT EXISTS marketing.topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    pillar VARCHAR(100) NOT NULL,  -- Product, Thought Leadership, Engineering, etc.
    audience_segment VARCHAR(100),  -- Enterprise, SMB, Developers, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_topics_pillar ON marketing.topics(pillar);
CREATE INDEX idx_topics_audience ON marketing.topics(audience_segment);
CREATE INDEX idx_topics_name ON marketing.topics(name);

-- 3. Content pillars (branding)
CREATE TABLE IF NOT EXISTS marketing.content_pillars (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7),  -- Hex color #RRGGBB
    target_audience VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_content_pillars_name ON marketing.content_pillars(name);

-- 4. Marketing drafts
CREATE TABLE IF NOT EXISTS marketing.drafts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    summary VARCHAR(500),
    
    -- Relationships
    topic_id INTEGER REFERENCES marketing.topics(id) ON DELETE SET NULL,
    signal_id INTEGER REFERENCES marketing.signals(id) ON DELETE SET NULL,
    
    -- Platform & publishing
    platform VARCHAR(50) DEFAULT 'blog',  -- blog, linkedin, twitter, email
    status VARCHAR(50) DEFAULT 'draft',  -- draft, review, approved, scheduled, published, archived
    
    -- Ghost integration
    ghost_post_id VARCHAR(255) UNIQUE,
    ghost_url VARCHAR(1024),
    
    -- SEO
    seo_title VARCHAR(255),
    seo_description VARCHAR(160),
    
    -- Metadata
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    metadata JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    
    CONSTRAINT chk_status CHECK (status IN ('draft', 'review', 'approved', 'scheduled', 'published', 'archived')),
    CONSTRAINT chk_platform CHECK (platform IN ('blog', 'linkedin', 'twitter', 'email'))
);

CREATE INDEX idx_drafts_status ON marketing.drafts(status);
CREATE INDEX idx_drafts_created_at ON marketing.drafts(created_at DESC);
CREATE INDEX idx_drafts_topic_id ON marketing.drafts(topic_id);
CREATE INDEX idx_drafts_signal_id ON marketing.drafts(signal_id);
CREATE INDEX idx_drafts_status_created ON marketing.drafts(status, created_at DESC);
CREATE INDEX idx_drafts_published_at ON marketing.drafts(published_at DESC);
CREATE INDEX idx_drafts_ghost_post_id ON marketing.drafts(ghost_post_id);

-- 5. Blog posts (published)
CREATE TABLE IF NOT EXISTS marketing.blog_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    ghost_post_id VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    published_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blog_posts_draft_id ON marketing.blog_posts(draft_id);
CREATE INDEX idx_blog_posts_ghost_post_id ON marketing.blog_posts(ghost_post_id);
CREATE INDEX idx_blog_posts_published_at ON marketing.blog_posts(published_at DESC);
CREATE INDEX idx_blog_posts_slug ON marketing.blog_posts(slug);

-- 6. LinkedIn posts
CREATE TABLE IF NOT EXISTS marketing.linkedin_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    hook VARCHAR(500),  -- Opening line
    linkedin_post_id VARCHAR(255),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_linkedin_posts_draft_id ON marketing.linkedin_posts(draft_id);
CREATE INDEX idx_linkedin_posts_posted_at ON marketing.linkedin_posts(posted_at DESC);

-- 7. Voice rules (brand guidelines)
CREATE TABLE IF NOT EXISTS marketing.voice_rules (
    id SERIAL PRIMARY KEY,
    rule_type VARCHAR(50) NOT NULL,  -- never_say, always_say
    content VARCHAR(500) NOT NULL,  -- The actual rule
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_rule_type CHECK (rule_type IN ('never_say', 'always_say'))
);

CREATE INDEX idx_voice_rules_type ON marketing.voice_rules(rule_type);
CREATE INDEX idx_voice_rules_created_at ON marketing.voice_rules(created_at DESC);

-- 8. Performance snapshots (analytics)
CREATE TABLE IF NOT EXISTS marketing.performance_snapshots (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES marketing.blog_posts(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,  -- plausible, ghost, linkedin
    views INTEGER DEFAULT 0,
    engagement_rate DECIMAL(5,2),  -- 0.00-100.00
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT chk_engagement CHECK (engagement_rate >= 0 AND engagement_rate <= 100)
);

CREATE INDEX idx_perf_post_id ON marketing.performance_snapshots(post_id);
CREATE INDEX idx_perf_platform ON marketing.performance_snapshots(platform);
CREATE INDEX idx_perf_recorded_at ON marketing.performance_snapshots(recorded_at DESC);
CREATE INDEX idx_perf_platform_recorded ON marketing.performance_snapshots(platform, recorded_at DESC);

-- Grant permissions (adjust role as needed)
GRANT ALL PRIVILEGES ON SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA marketing TO homelab;

-- Initial data: seed some content pillars
INSERT INTO marketing.content_pillars (name, description, color, target_audience) VALUES
    ('Product', 'Product features, releases, roadmap', '#0066cc', 'All'),
    ('Engineering', 'Technical deep-dives, architecture, best practices', '#009900', 'Engineers'),
    ('Thought Leadership', 'Industry insights, strategy, vision', '#ff9900', 'Decision makers'),
    ('Culture', 'Team, company culture, events', '#ff0066', 'All')
ON CONFLICT (name) DO NOTHING;

-- Seed initial voice rules
INSERT INTO marketing.voice_rules (rule_type, content) VALUES
    ('always_say', 'Use "we" and "our" when referring to the company'),
    ('always_say', 'Be clear, concise, and avoid jargon'),
    ('never_say', 'Don''t make unsubstantiated claims about competitors'),
    ('never_say', 'Don''t use ALL CAPS except for acronyms')
ON CONFLICT DO NOTHING;
