-- Marketing Agent Initial Schema
-- Creates 8 tables for marketing pipeline

CREATE SCHEMA IF NOT EXISTS marketing;

-- 1. Signals Table
CREATE TABLE marketing.signals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    source VARCHAR(128) NOT NULL,
    relevance_score FLOAT NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kg_node_id VARCHAR(128),
    INDEX idx_title (title),
    INDEX idx_kg_node_id (kg_node_id),
    INDEX idx_created_at (created_at)
);

-- 2. Content Pillars Table
CREATE TABLE marketing.content_pillars (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7),
    target_audience VARCHAR(255) NOT NULL,
    INDEX idx_name (name)
);

-- 3. Topics Table
CREATE TABLE marketing.topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    pillar VARCHAR(255) NOT NULL,
    audience_segment VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name),
    INDEX idx_created_at (created_at)
);

-- 4. Drafts Table
CREATE TABLE marketing.drafts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    topic_id INTEGER REFERENCES marketing.topics(id),
    platform VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_title (title),
    INDEX idx_status (status),
    INDEX idx_topic_id (topic_id),
    INDEX idx_platform (platform),
    INDEX idx_created_at (created_at)
);

-- 5. Blog Posts Table
CREATE TABLE marketing.blog_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE,
    ghost_post_id VARCHAR(64) NOT NULL UNIQUE,
    published_at TIMESTAMP,
    slug VARCHAR(255) NOT NULL UNIQUE,
    tags VARCHAR(512),
    FOREIGN KEY (draft_id) REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    INDEX idx_ghost_post_id (ghost_post_id),
    INDEX idx_slug (slug)
);

-- 6. LinkedIn Posts Table
CREATE TABLE marketing.linkedin_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL,
    hook VARCHAR(512),
    posted_at TIMESTAMP,
    FOREIGN KEY (draft_id) REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    INDEX idx_posted_at (posted_at)
);

-- 7. Voice Rules Table
CREATE TABLE marketing.voice_rules (
    id SERIAL PRIMARY KEY,
    rule_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rule_type (rule_type),
    INDEX idx_created_at (created_at)
);

-- 8. Performance Snapshots Table
CREATE TABLE marketing.performance_snapshots (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    platform VARCHAR(64) NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    engagement_rate FLOAT NOT NULL DEFAULT 0.0,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_post_id (post_id),
    INDEX idx_platform (platform),
    INDEX idx_recorded_at (recorded_at)
);

-- Grant permissions if needed (adjust user as needed)
-- GRANT ALL PRIVILEGES ON marketing.* TO 'homelab'@'%';
-- FLUSH PRIVILEGES;
