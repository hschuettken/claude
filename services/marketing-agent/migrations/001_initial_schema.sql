-- Marketing Agent Initial Schema
-- Creates 8 tables for marketing pipeline
-- PostgreSQL syntax

CREATE SCHEMA IF NOT EXISTS marketing;

-- 1. Signals Table
CREATE TABLE marketing.signals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    source VARCHAR(128) NOT NULL,
    relevance_score FLOAT NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kg_node_id VARCHAR(128)
);
CREATE INDEX idx_signals_title ON marketing.signals(title);
CREATE INDEX idx_signals_kg_node_id ON marketing.signals(kg_node_id);
CREATE INDEX idx_signals_created_at ON marketing.signals(created_at);

-- 2. Content Pillars Table
CREATE TABLE marketing.content_pillars (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7),
    target_audience VARCHAR(255) NOT NULL
);
CREATE INDEX idx_content_pillars_name ON marketing.content_pillars(name);

-- 3. Topics Table
CREATE TABLE marketing.topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    pillar VARCHAR(255) NOT NULL,
    audience_segment VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_topics_name ON marketing.topics(name);
CREATE INDEX idx_topics_created_at ON marketing.topics(created_at);

-- 4. Drafts Table
CREATE TABLE marketing.drafts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    topic_id INTEGER REFERENCES marketing.topics(id),
    platform VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_drafts_title ON marketing.drafts(title);
CREATE INDEX idx_drafts_status ON marketing.drafts(status);
CREATE INDEX idx_drafts_topic_id ON marketing.drafts(topic_id);
CREATE INDEX idx_drafts_platform ON marketing.drafts(platform);
CREATE INDEX idx_drafts_created_at ON marketing.drafts(created_at);

-- 5. Blog Posts Table
CREATE TABLE marketing.blog_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE,
    ghost_post_id VARCHAR(64) NOT NULL UNIQUE,
    published_at TIMESTAMP,
    slug VARCHAR(255) NOT NULL UNIQUE,
    tags VARCHAR(512),
    FOREIGN KEY (draft_id) REFERENCES marketing.drafts(id) ON DELETE CASCADE
);
CREATE INDEX idx_blog_posts_ghost_post_id ON marketing.blog_posts(ghost_post_id);
CREATE INDEX idx_blog_posts_slug ON marketing.blog_posts(slug);

-- 6. LinkedIn Posts Table
CREATE TABLE marketing.linkedin_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL,
    hook VARCHAR(512),
    posted_at TIMESTAMP,
    FOREIGN KEY (draft_id) REFERENCES marketing.drafts(id) ON DELETE CASCADE
);
CREATE INDEX idx_linkedin_posts_posted_at ON marketing.linkedin_posts(posted_at);

-- 7. Voice Rules Table
CREATE TABLE marketing.voice_rules (
    id SERIAL PRIMARY KEY,
    rule_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_voice_rules_rule_type ON marketing.voice_rules(rule_type);
CREATE INDEX idx_voice_rules_created_at ON marketing.voice_rules(created_at);

-- 8. Performance Snapshots Table
CREATE TABLE marketing.performance_snapshots (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    platform VARCHAR(64) NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    engagement_rate FLOAT NOT NULL DEFAULT 0.0,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_performance_snapshots_post_id ON marketing.performance_snapshots(post_id);
CREATE INDEX idx_performance_snapshots_platform ON marketing.performance_snapshots(platform);
CREATE INDEX idx_performance_snapshots_recorded_at ON marketing.performance_snapshots(recorded_at);
