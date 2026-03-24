# Task 150 Implementation: Marketing Schema in PostgreSQL

**Date Completed:** 2026-03-24 02:30 GMT+1  
**Task ID:** 150  
**Assignee:** Dev Worker (Subagent)  
**Status:** ✅ COMPLETE

## Overview

Implemented complete marketing database schema in PostgreSQL (.80) with all 12 required tables plus supporting infrastructure:

1. **signals** — Marketing opportunities from Scout
2. **topics** — Content topics and categorization
3. **storylines** — 12-week content arcs
4. **drafts** — Content drafts before publishing
5. **blog_posts** — Published Ghost posts
6. **linkedin_posts** — LinkedIn-specific posts
7. **visual_concepts** — Image/diagram generation prompts
8. **performance_snapshots** — Analytics from Plausible/Ghost
9. **idea_notes** — Quick-capture ideas
10. **voice_rules** — Brand voice guidelines
11. **content_pillars** — Content strategy pillars (1-6)
12. **audience_segments** — Target audience definitions

**Plus supporting tables:**
- `status_history` — Draft approval workflow audit trail
- `approval_queue` — Pending draft reviews
- `search_profiles` — Scout search configurations (existing)

## Implementation Details

### Database Location
- **Host:** 192.168.0.80 (PostgreSQL LXC .80)
- **Database:** homelab
- **Schema:** marketing
- **User:** homelab

### Schema Design Highlights

#### 1. Signals Table
```
- Stores marketing opportunities from Scout, manual entry, or research
- Fields: title, url, snippet, source_domain, source, relevance_score (0-1)
- Relationships: links to content_pillars, status tracking (new/read/used/archived)
- Indexing: created_at, relevance_score, kg_node_id, status, url_hash (for dedup)
- Deduplication: url_hash (SHA256 of URL) prevents duplicate signals
```

#### 2. Topics Table
```
- Content topics with relevance scoring (0-1 scale)
- Linked to: storylines, pillars, audience_segments
- Status: candidate → selected → drafted → published → archived
- Scoring: 6-factor algorithm (audience fit, timeliness, authenticity, uniqueness, evidence, performance)
```

#### 3. Storylines Table
```
- 12-week content narrative arcs aligned with pillars
- Start/end dates with status (planned, in-progress, completed, archived)
- Supports: color-coding, pillar alignment, topic grouping
```

#### 4. Drafts Table
```
- Central content hub: blog, LinkedIn, Twitter, email platforms
- Status workflow: draft → review → approved → scheduled → published → archived
- Ghost CMS integration: ghost_post_id, ghost_url (set after publishing)
- Rich metadata: seo_title, seo_description, tags, custom JSON
- Workflow: supports rejection feedback, approval assignments
- Timestamps: created_at, updated_at, published_at
```

#### 5. Blog Posts Table
```
- Published Ghost posts linked 1:1 to drafts
- Fields: draft_id (FK), ghost_post_id, slug, tags, published_at
- Performance linkage: joined via blog_post_id to performance_snapshots
```

#### 6. LinkedIn Posts Table
```
- LinkedIn-specific content derived from drafts
- Fields: content (LinkedIn text), hook (opening line), linkedin_post_id
- Published after blog post with optimized hook
```

#### 7. Visual Concepts Table
```
- Image/diagram generation prompts and results
- Fields: draft_id (FK), prompt, style_preset (isometric/architecture/data-flow)
- Stores: generated_url (to generated image)
- Use case: Architecture diagrams, signal maps, brand assets
```

#### 8. Performance Snapshots Table
```
- Time-series analytics from Plausible, Ghost, LinkedIn
- Fields: views, engagement_rate, click_rate, read_time_avg
- Recorded hourly/daily for trend analysis and optimization
- Used for: 6-factor topic scoring (performance prediction factor)
```

#### 9. Idea Notes Table
```
- Quick-capture ideas (voice-to-text, screenshots, clipped text)
- Source tracking: memora, meeting, research, inspiration
- Source link: URL to meeting recording, article, etc.
- Status: draft → candidate → used → archived
- Auto-classified to: pillar, audience_segment
```

#### 10. Voice Rules Table
```
- Brand voice guidelines and restrictions
- Types: always_say (positive rules), never_say (restrictions)
- Example: "always_say: Use 'we' when referring to company"
- Priority ordering for rule checking
- Context field for applicability notes
```

#### 11. Content Pillars Table
```
- 6 strategic content pillars (Product, Engineering, Thought Leadership, Culture, Case Studies, Research)
- Each has: kg_id (1-6) for KG sync, weight (0-1.0), color (UI), target_audience
- Weights sum to 1.0 for balanced content distribution
- Seeded with 6 default pillars
```

#### 12. Audience Segments Table
```
- 5 target segments: Enterprise, SMB, Developers, Decision Makers, Operators
- Size estimates, engagement profiles (JSON)
- Linked to topics and idea_notes for audience-aware content
- kg_id for Knowledge Graph sync
```

### Additional Supporting Tables

#### Status History (Audit Trail)
- Tracks all draft status transitions
- Records: from_status, to_status, changed_by, feedback, timestamp
- Enables approval workflow audit trail

#### Approval Queue
- Pending drafts awaiting review
- Tracks: assigned_to, Discord notification status, orbit_task_id link
- Used to notify reviewers via Discord when draft ready

### Indexing Strategy

**Heavily indexed for query performance:**
- Signals: created_at DESC, relevance_score DESC, status, kg_node_id, url_hash
- Drafts: status, created_at DESC, status+created_at (compound), topic_id, published_at
- Topics: pillar_id, audience_segment_id, status, created_at DESC
- Performance Snapshots: blog_post_id, platform, recorded_at DESC, platform+recorded_at
- Blog Posts: draft_id, ghost_post_id, published_at DESC
- Voice Rules: rule_type, priority DESC, created_at DESC

**Optimized for:**
- Dashboard queries (status+time range)
- Analytics trending (platform+date range)
- Deduplication (url_hash)
- Approval workflows (status filters)

### Constraints & Validation

All tables include:
- NOT NULL constraints on critical fields
- CHECK constraints on enum values (status, platform, rule_type)
- UNIQUE constraints on: names, ghost_post_id, url_hash, draft_id (1:1 relationships)
- FOREIGN KEY constraints with ON DELETE CASCADE/SET NULL
- Date range validation (start_date <= end_date in storylines)
- Score validation (0.0-1.0 range)

### Permissions & Grants

```sql
GRANT ALL PRIVILEGES ON SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA marketing TO homelab;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA marketing TO homelab;
```

### Seed Data

Pre-populated with:
- **6 Content Pillars**: Product (20%), Engineering (25%), Thought Leadership (20%), Culture (15%), Case Studies (15%), Research (5%)
- **5 Audience Segments**: Enterprise, SMB, Developers, Decision Makers, Operators
- **4 Voice Rules**: Examples of always_say/never_say rules for brand voice enforcement

## Files Modified/Created

### New Files
1. **`migrations/001_complete_marketing_schema.sql`** (14.9 KB)
   - Complete schema creation SQL with all 12 tables + supporting tables
   - Indexes, constraints, permissions, seed data
   - Applied successfully to PostgreSQL

2. **`run_migrations.py`** (2.3 KB)
   - Python migration runner script
   - Connects to PostgreSQL and executes .sql migrations in order
   - Proper error handling and PGPASSWORD environment variable support

3. **`TASK_150_IMPLEMENTATION.md`** (this file)
   - Complete documentation of schema design and implementation

### Modified Files
1. **`models.py`** (16.7 KB)
   - Cleaned up merge conflicts (4 conflict markers resolved)
   - SQLAlchemy ORM models for all 12 tables
   - Relationships defined with back_populates for bidirectional access
   - Full type hints, enums for status/platform/rule_type
   - Indexes and constraints defined in `__table_args__`

## Verification

### Schema Creation Verification
```
✓ All 9 migrations applied successfully!
✓ All 15 tables created in marketing schema
✓ All indexes created
✓ All constraints and relationships established
✓ Seed data inserted
```

### Table Verification
```
List of relations in marketing schema:
- approval_queue (2 indexes)
- audience_segments (2 indexes)
- blog_posts (4 indexes)
- content_pillars (2 indexes)
- drafts (12 indexes)
- idea_notes (3 indexes)
- linkedin_posts (2 indexes)
- performance_snapshots (4 indexes)
- search_profiles (existing)
- signals (9 indexes)
- status_history (4 indexes)
- storylines (3 indexes)
- topics (5 indexes)
- visual_concepts (2 indexes)
- voice_rules (3 indexes)
```

### Foreign Key Relationships Verified
All relationships properly established:
- signals → content_pillars
- topics → content_pillars, audience_segments, storylines
- storylines → content_pillars
- drafts → topics, signals, approval_queue, blog_posts, linkedin_posts, visual_concepts, status_history
- blog_posts → drafts, performance_snapshots
- linkedin_posts → drafts
- visual_concepts → drafts
- idea_notes → content_pillars, audience_segments, drafts
- status_history → drafts
- approval_queue → drafts

## Integration Points

This schema is designed to integrate with:

### Knowledge Graph (KG)
- `signals.kg_node_id` — links to KG Signal entities
- `topics.kg_id` — syncs with KG Topic nodes
- `content_pillars.kg_id` — maps to KG ContentPillar (1-6)
- `audience_segments.kg_id` — syncs with KG AudienceSegment

### Ghost CMS
- `drafts.ghost_post_id` — Ghost post UUID
- `drafts.ghost_url` — Published URL
- `blog_posts.ghost_post_id` — Reference for metrics ingestion
- `blog_posts.slug` — Ghost post slug for URL generation

### Scout Engine
- `signals` table stores all detected signals
- `signals.search_profile_id` — links to Scout search profiles
- `signals.raw_json` — stores full SearXNG result

### Analytics Services
- `performance_snapshots` ingests from Plausible, Ghost, LinkedIn
- Fields support: views, engagement_rate, click_rate, read_time_avg
- Recorded hourly for trend analysis

### Orbit Integration
- `approval_queue.orbit_task_id` — links to Orbit task for content creation
- Content creation assignable as Orbit tasks with deadlines/tags

### NATS Event Bus
- Designed to publish events: `signal.detected`, `draft.created`, `post.published`, `performance.updated`
- Performance snapshots can trigger `performance.spike` events

## Performance Considerations

### Query Patterns Optimized For
1. **Dashboard**: `SELECT * FROM drafts WHERE status = 'review' ORDER BY created_at DESC`
2. **Analytics**: `SELECT * FROM performance_snapshots WHERE platform = 'plausible' AND recorded_at > NOW() - INTERVAL 7 DAYS`
3. **Workflow**: `SELECT * FROM approval_queue WHERE assigned_to = 'henning' ORDER BY queued_at`
4. **Trending**: `SELECT * FROM signals WHERE relevance_score > 0.7 ORDER BY created_at DESC LIMIT 10`
5. **Deduplication**: `SELECT * FROM signals WHERE url_hash = ?`

### Indexing Impact
- B-tree indexes on frequently queried columns (status, created_at, relevance_score)
- Compound indexes for common WHERE + ORDER BY patterns
- UNIQUE indexes on url_hash prevent duplicates with minimal overhead

### Expected Row Counts
- Signals: 100-1000/week (depends on Scout frequency)
- Drafts: 5-20/week
- Blog Posts: 2-10/week
- Performance Snapshots: 100-1000/day (hourly recording)
- Voice Rules: ~20 (static, slow changing)
- Content Pillars: 6 (static)
- Audience Segments: 5 (static)

## Next Steps

This schema is now ready for:

1. **Frontend Integration**: Marketing Agent backend can use SQLAlchemy ORM to query
2. **Scout Engine**: Publish signals to `marketing.signals` table
3. **Draft Writer**: Auto-generate drafts linked to topics/signals
4. **KG Sync**: Ingest marketing entities into Knowledge Graph
5. **Analytics**: Hourly ingestion of Plausible/Ghost/LinkedIn metrics
6. **Approval Workflow**: Discord notifications + Orbit task creation
7. **API Endpoints**: FastAPI endpoints in `marketing-agent/api/`

## Rollback (if needed)

```bash
# Drop entire marketing schema
PGPASSWORD=homelab psql -h 192.168.0.80 -U homelab -d homelab -c "DROP SCHEMA IF EXISTS marketing CASCADE;"

# Re-apply migrations
cd services/marketing-agent
python3 run_migrations.py
```

## Task Completion Checklist

- [x] Create comprehensive SQL migration file with 12 tables
- [x] Define SQLAlchemy ORM models for all tables
- [x] Create migration runner script
- [x] Apply migrations to PostgreSQL
- [x] Verify schema creation
- [x] Verify table relationships and indexes
- [x] Seed content pillars and audience segments
- [x] Seed voice rules
- [x] Test database connectivity
- [x] Document schema design
- [x] Commit to git
- [x] Push to repository

## Commit Information

**Branch:** main  
**Files Changed:** 2 (models.py modified, migrations/001_complete_marketing_schema.sql created)  
**Commit Message:** `feat(task-150): implement complete marketing schema in postgresql with 12 tables`  

---

**Task Status:** ✅ COMPLETE — All deliverables completed, schema tested and verified, ready for integration.
