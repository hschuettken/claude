-- Migration: Complete Marketing Schema (12 tables)
-- Creates all tables for marketing signals, topics, storylines, drafts, posts, and analytics

CREATE SCHEMA IF NOT EXISTS marketing;

-- ====== 1. CONTENT PILLARS (base reference) ======
CREATE TABLE IF NOT EXISTS marketing.content_pillars (
    id SERIAL PRIMARY KEY,
    kg_id INTEGER UNIQUE,  -- KG pillar ID (1-6) for cross-system linking
    name VARCHAR(255) NOT NULL UNIQUE,
    weight DECIMAL(5,2) DEFAULT 0.0,  -- Pillar weight in distribution (sums to 1.0)
    description TEXT,
    color VARCHAR(7),  -- Hex color for UI (e.g., #0066cc)
    target_audience VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_content_pillars_name ON marketing.content_pillars(name);
CREATE INDEX idx_content_pillars_kg_id ON marketing.content_pillars(kg_id);

-- ====== 2. AUDIENCE SEGMENTS ======
CREATE TABLE IF NOT EXISTS marketing.audience_segments (
    id SERIAL PRIMARY KEY,
    kg_id INTEGER UNIQUE,  -- KG audience segment ID
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    size_estimate INTEGER,  -- Estimated audience size
    engagement_profile JSONB DEFAULT '{}',  -- Preferences, channels, interests
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audience_segments_name ON marketing.audience_segments(name);
CREATE INDEX idx_audience_segments_kg_id ON marketing.audience_segments(kg_id);

-- ====== 3. MARKETING SIGNALS ======
CREATE TABLE IF NOT EXISTS marketing.signals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(1024),
    snippet TEXT,  -- Content snippet from search result
    source_domain VARCHAR(255),  -- e.g., sap.com, linkedin.com
    source VARCHAR(100) NOT NULL,  -- scout, manual, research, etc.
    relevance_score DECIMAL(3,2) DEFAULT 0.0,  -- 0.00-1.00
    pillar_id INTEGER REFERENCES marketing.content_pillars(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'new',  -- new, read, used, archived
    kg_node_id VARCHAR(100),  -- Reference to KG node
    url_hash VARCHAR(64) UNIQUE,  -- sha256(url) for deduplication
    search_profile_id VARCHAR(100),  -- Profile that detected this signal
    raw_json JSONB,  -- Full SearXNG result JSON
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_relevance CHECK (relevance_score >= 0 AND relevance_score <= 1),
    CONSTRAINT chk_signal_status CHECK (status IN ('new', 'read', 'used', 'archived'))
);

CREATE INDEX idx_signals_created_at ON marketing.signals(created_at DESC);
CREATE INDEX idx_signals_relevance ON marketing.signals(relevance_score DESC);
CREATE INDEX idx_signals_kg_node ON marketing.signals(kg_node_id);
CREATE INDEX idx_signals_status ON marketing.signals(status);
CREATE INDEX idx_signals_pillar ON marketing.signals(pillar_id);
CREATE INDEX idx_signals_url_hash ON marketing.signals(url_hash);
CREATE INDEX idx_signals_source ON marketing.signals(source);
CREATE INDEX idx_signals_detected_at ON marketing.signals(detected_at DESC);

-- ====== 4. STORYLINES (12-week content arcs) ======
CREATE TABLE IF NOT EXISTS marketing.storylines (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    pillar_id INTEGER REFERENCES marketing.content_pillars(id) ON DELETE SET NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    status VARCHAR(50) DEFAULT 'planned',  -- planned, in-progress, completed, archived
    color VARCHAR(7),  -- Hex color for UI
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_storyline_status CHECK (status IN ('planned', 'in-progress', 'completed', 'archived')),
    CONSTRAINT chk_date_range CHECK (start_date <= end_date)
);

CREATE INDEX idx_storylines_start_date ON marketing.storylines(start_date);
CREATE INDEX idx_storylines_pillar_id ON marketing.storylines(pillar_id);
CREATE INDEX idx_storylines_status ON marketing.storylines(status);

-- ====== 5. TOPICS ======
CREATE TABLE IF NOT EXISTS marketing.topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    kg_id INTEGER,  -- KG topic ID for cross-system linking
    pillar_id INTEGER REFERENCES marketing.content_pillars(id) ON DELETE SET NULL,
    score DECIMAL(5,2) DEFAULT 0.0,  -- Topic relevance/viability score (0.00-1.00)
    summary TEXT,  -- Topic summary/context for draft writer
    status VARCHAR(50) DEFAULT 'candidate',  -- candidate, selected, drafted, published, archived
    audience_segment_id INTEGER REFERENCES marketing.audience_segments(id) ON DELETE SET NULL,
    storyline_id INTEGER REFERENCES marketing.storylines(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_topic_status CHECK (status IN ('candidate', 'selected', 'drafted', 'published', 'archived')),
    CONSTRAINT chk_topic_score CHECK (score >= 0 AND score <= 1)
);

CREATE INDEX idx_topics_pillar ON marketing.topics(pillar_id);
CREATE INDEX idx_topics_audience ON marketing.topics(audience_segment_id);
CREATE INDEX idx_topics_status ON marketing.topics(status);
CREATE INDEX idx_topics_created_at ON marketing.topics(created_at DESC);
CREATE INDEX idx_topics_storyline_id ON marketing.topics(storyline_id);
CREATE INDEX idx_topics_name ON marketing.topics(name);

-- ====== 6. IDEA NOTES (quick-capture) ======
CREATE TABLE IF NOT EXISTS marketing.idea_notes (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT,
    pillar_id INTEGER REFERENCES marketing.content_pillars(id) ON DELETE SET NULL,
    audience_segment_id INTEGER REFERENCES marketing.audience_segments(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'draft',  -- draft, candidate, used, archived
    source VARCHAR(100),  -- memora, meeting, research, inspiration, etc.
    source_link VARCHAR(1024),  -- Link to source (meeting recording, article, etc.)
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_idea_notes_status ON marketing.idea_notes(status);
CREATE INDEX idx_idea_notes_pillar_id ON marketing.idea_notes(pillar_id);
CREATE INDEX idx_idea_notes_created_at ON marketing.idea_notes(created_at DESC);

-- ====== 7. DRAFTS ======
CREATE TABLE IF NOT EXISTS marketing.drafts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    summary VARCHAR(500),
    topic_id INTEGER REFERENCES marketing.topics(id) ON DELETE SET NULL,
    signal_id INTEGER REFERENCES marketing.signals(id) ON DELETE SET NULL,
    platform VARCHAR(50) DEFAULT 'blog',  -- blog, linkedin, twitter, email
    status VARCHAR(50) DEFAULT 'draft',  -- draft, review, approved, scheduled, published, archived
    ghost_post_id VARCHAR(255) UNIQUE,  -- Set after publishing to Ghost
    ghost_url VARCHAR(1024),
    rejection_feedback TEXT,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    seo_title VARCHAR(255),
    seo_description VARCHAR(160),
    extra_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    CONSTRAINT chk_draft_status CHECK (status IN ('draft', 'review', 'approved', 'scheduled', 'published', 'archived')),
    CONSTRAINT chk_draft_platform CHECK (platform IN ('blog', 'linkedin', 'twitter', 'email'))
);

CREATE INDEX idx_drafts_status ON marketing.drafts(status);
CREATE INDEX idx_drafts_created_at ON marketing.drafts(created_at DESC);
CREATE INDEX idx_drafts_topic_id ON marketing.drafts(topic_id);
CREATE INDEX idx_drafts_signal_id ON marketing.drafts(signal_id);
CREATE INDEX idx_drafts_status_created ON marketing.drafts(status, created_at DESC);
CREATE INDEX idx_drafts_published_at ON marketing.drafts(published_at DESC);
CREATE INDEX idx_drafts_ghost_post_id ON marketing.drafts(ghost_post_id);

-- ====== 8. BLOG POSTS ======
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

-- ====== 9. LINKEDIN POSTS ======
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

-- ====== 10. VISUAL CONCEPTS ======
CREATE TABLE IF NOT EXISTS marketing.visual_concepts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,  -- Image generation prompt
    style_preset VARCHAR(100),  -- isometric, architecture, data-flow, etc.
    generated_url VARCHAR(1024),  -- URL to generated image
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_visual_concepts_draft_id ON marketing.visual_concepts(draft_id);
CREATE INDEX idx_visual_concepts_created_at ON marketing.visual_concepts(created_at DESC);

-- ====== 11. PERFORMANCE SNAPSHOTS ======
CREATE TABLE IF NOT EXISTS marketing.performance_snapshots (
    id SERIAL PRIMARY KEY,
    blog_post_id INTEGER NOT NULL REFERENCES marketing.blog_posts(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,  -- plausible, ghost, linkedin
    views INTEGER DEFAULT 0,
    engagement_rate DECIMAL(5,2),  -- 0.00-100.00
    click_rate DECIMAL(5,2),  -- 0.00-100.00
    read_time_avg DECIMAL(8,2),  -- Average reading time in seconds
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    extra_data JSONB DEFAULT '{}',  -- Raw analytics data
    CONSTRAINT chk_engagement CHECK (engagement_rate >= 0 AND engagement_rate <= 100),
    CONSTRAINT chk_click_rate CHECK (click_rate >= 0 AND click_rate <= 100)
);

CREATE INDEX idx_perf_post_id ON marketing.performance_snapshots(blog_post_id);
CREATE INDEX idx_perf_platform ON marketing.performance_snapshots(platform);
CREATE INDEX idx_perf_recorded_at ON marketing.performance_snapshots(recorded_at DESC);
CREATE INDEX idx_perf_platform_recorded ON marketing.performance_snapshots(platform, recorded_at DESC);

-- ====== 12. VOICE RULES ======
CREATE TABLE IF NOT EXISTS marketing.voice_rules (
    id SERIAL PRIMARY KEY,
    rule_type VARCHAR(50) NOT NULL,  -- never_say, always_say
    content VARCHAR(500) NOT NULL,  -- The actual rule text
    context VARCHAR(255),  -- Where/how the rule applies
    priority INTEGER DEFAULT 0,  -- Higher priority rules checked first
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_voice_rule_type CHECK (rule_type IN ('never_say', 'always_say'))
);

CREATE INDEX idx_voice_rules_type ON marketing.voice_rules(rule_type);
CREATE INDEX idx_voice_rules_created_at ON marketing.voice_rules(created_at DESC);
CREATE INDEX idx_voice_rules_priority ON marketing.voice_rules(priority DESC);

-- ====== AUDIT: STATUS HISTORY ======
CREATE TABLE IF NOT EXISTS marketing.status_history (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    from_status VARCHAR(50),  -- NULL for initial status
    to_status VARCHAR(50) NOT NULL,
    changed_by VARCHAR(255),  -- User who made the transition
    feedback TEXT,  -- Rejection feedback or notes
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_status_history_draft_id ON marketing.status_history(draft_id);
CREATE INDEX idx_status_history_created_at ON marketing.status_history(created_at DESC);
CREATE INDEX idx_status_history_to_status ON marketing.status_history(to_status);
CREATE INDEX idx_status_history_draft_created ON marketing.status_history(draft_id, created_at DESC);

-- ====== APPROVAL QUEUE ======
CREATE TABLE IF NOT EXISTS marketing.approval_queue (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_to VARCHAR(255),  -- Who it's assigned to (e.g., "henning")
    orbit_task_id VARCHAR(255),  -- Link to Orbit task
    discord_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_approval_queue_queued_at ON marketing.approval_queue(queued_at);
CREATE INDEX idx_approval_queue_assigned_to ON marketing.approval_queue(assigned_to);
CREATE INDEX idx_approval_queue_orbit_task_id ON marketing.approval_queue(orbit_task_id);

-- ====== PERMISSIONS ======
GRANT ALL PRIVILEGES ON SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA marketing TO homelab;

-- ====== SEED DATA ======
INSERT INTO marketing.content_pillars (kg_id, name, weight, description, color, target_audience) VALUES
    (1, 'Product', 0.20, 'Product features, releases, roadmap', '#0066cc', 'All'),
    (2, 'Engineering', 0.25, 'Technical deep-dives, architecture, best practices', '#009900', 'Engineers'),
    (3, 'Thought Leadership', 0.20, 'Industry insights, strategy, vision', '#ff9900', 'Decision makers'),
    (4, 'Culture', 0.15, 'Team, company culture, events', '#ff0066', 'All'),
    (5, 'Case Studies', 0.15, 'Customer stories, implementation insights', '#6600cc', 'Enterprise'),
    (6, 'Research', 0.05, 'Original research, data, trends', '#cc6600', 'Data professionals')
ON CONFLICT (kg_id) DO NOTHING;

INSERT INTO marketing.audience_segments (kg_id, name, description, size_estimate) VALUES
    (1, 'Enterprise', 'Large organizations with complex SAP landscapes', 50000),
    (2, 'SMB', 'Small and medium businesses', 100000),
    (3, 'Developers', 'Technical developers and architects', 30000),
    (4, 'Decision Makers', 'C-suite and business leaders', 20000),
    (5, 'Operators', 'SAP operations and platform teams', 40000)
ON CONFLICT (kg_id) DO NOTHING;

INSERT INTO marketing.voice_rules (rule_type, content, context, priority) VALUES
    ('always_say', 'Use "we" and "our" when referring to the company', 'General', 1),
    ('always_say', 'Be clear, concise, and avoid jargon', 'General', 1),
    ('never_say', 'Don''t make unsubstantiated claims about competitors', 'Competitive', 2),
    ('never_say', 'Don''t use ALL CAPS except for acronyms', 'Style', 0)
ON CONFLICT DO NOTHING;
