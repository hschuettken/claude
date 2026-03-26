# Newsletter Engine — Task 187

## Overview

The **Newsletter Engine** provides automated monthly newsletter generation for the **Layer 8** personal thought-leadership brand. It automatically compiles published posts, market signals, and draft ideas into a professional, brand-consistent HTML newsletter ready for Ghost CMS distribution.

## Features

### 1. **Automated Monthly Compilation**
- Gathers all published blog posts from a calendar month
- Aggregates high-relevance market signals and insights
- Selects promising draft ideas for subscriber feedback
- Computes monthly statistics (post count, reach, pillar distribution)

### 2. **Brand-Consistent Template**
- Layer 8 visual identity (blue #0066cc, clean typography)
- Professional HTML/CSS template optimized for email clients
- Responsive design for desktop and mobile
- Footer with branding and copyright

### 3. **Content Sections**
- **This Month's Posts** — Published blog posts with titles, excerpts, links, pillar tags, and dates
- **Market Insights & Signals** — High-relevance signals (≥0.7 score) from SearXNG monitoring
- **What's Coming** — Draft ideas in progress to solicit subscriber feedback

### 4. **Ghost CMS Integration**
- Publishes newsletter as a draft post in Ghost CMS
- Can be reviewed and modified before distribution
- Uses Ghost Newsletter feature to send to subscribed readers
- Integrates with Ghost's built-in analytics

## API Endpoints

### `POST /newsletters/generate`
Generate a new monthly newsletter.

**Request:**
```json
{
  "month_date": "2026-03-15",  // Optional, defaults to last month
  "publish_to_ghost": false     // If true, creates draft post in Ghost
}
```

**Response:**
```json
{
  "month": "March 2026",
  "subject_line": "Layer 8 Insights — March 2026",
  "hero_text": "Welcome to Layer 8 Insights...",
  "newsletter_html": "<html>...</html>",
  "monthly_stats": {
    "published_count": 4,
    "signal_count": 8,
    "draft_ideas_count": 2,
    "estimated_reach": 600,
    "content_pillars": {
      "SAP technical": 2,
      "Architecture": 1,
      "AI in enterprise": 1
    }
  },
  "created_at": "2026-03-25T10:30:00Z",
  "ghost_post_id": null
}
```

### `GET /newsletters`
List all generated newsletters.

**Response:**
```json
[
  {
    "month": "March 2026",
    "subject_line": "Layer 8 Insights — March 2026",
    "published_posts_count": 4,
    "featured_signals_count": 8,
    "draft_ideas_count": 2,
    "created_at": "2026-03-25T10:30:00Z",
    "ghost_post_id": "abc123",
    "published_posts": [...],
    "featured_signals": [...],
    "draft_ideas": [...]
  }
]
```

### `GET /newsletters/{id}`
Retrieve a specific newsletter.

### `POST /newsletters/{id}/publish`
Publish a newsletter to Ghost CMS.

### `POST /newsletters/{id}/send`
Send newsletter to Ghost subscribers via the Newsletter feature.

**Request:**
```json
{
  "test_email": "test@example.com"  // Optional, sends test first
}
```

## Data Sources

### 1. Published Posts
**Source:** `marketing_blog_posts` table

**Fields used:**
- `id` — Post ID
- `title` — Post title
- `slug` — URL slug
- `published_at` — Publication date
- `excerpt` — Short summary
- `pillar` — Content pillar category
- `status` — Post status (must be "published")

**Filtering:**
- Date range: Month start to month end
- Status: "published"
- Order: Most recent first

### 2. Market Signals
**Source:** `marketing_signals` table

**Fields used:**
- `id` — Signal ID
- `title` — Signal title
- `summary` — Signal description
- `source` — Signal source (e.g., "SAP News", "LinkedIn")
- `relevance_score` — Relevance (0.0–1.0)
- `created_at` — Detection date

**Filtering:**
- Date range: Month start to month end
- Status: "active"
- Relevance: ≥ 0.7
- Limit: Top 10 by relevance

### 3. Draft Ideas
**Source:** `marketing_drafts` table

**Fields used:**
- `id` — Draft ID
- `title` — Draft title
- `excerpt` — Draft summary
- `status` — Draft status
- `pillar` — Content pillar
- `created_at` — Creation date

**Filtering:**
- Date range: Month start to month end
- Status: "in_progress" or "awaiting_feedback"
- Limit: 3 most recent

## HTML Template Structure

The newsletter HTML is a self-contained, responsive email template with:

```
Header
├─ Layer 8 branding
├─ Month subtitle
└─ Blue accent border

Statistics Grid
├─ Posts Published
├─ Market Signals
└─ Draft Ideas

Section: This Month's Posts
├─ Item cards with:
│  ├─ Post title (linked)
│  ├─ Excerpt text
│  ├─ Pillar badge
│  └─ Publication date

Section: Market Insights & Signals
├─ Intro text about signals
└─ Signal items with:
   ├─ Title
   ├─ Summary
   ├─ Source badge
   └─ Relevance score

Section: What's Coming
├─ Intro text about drafts
└─ Draft items with:
   ├─ Title
   ├─ Summary
   ├─ Pillar badge
   └─ "Coming soon" status

Call-to-Action
├─ Link to main blog

Footer
├─ Branding
└─ Copyright
```

### CSS Styling

**Color Palette:**
- Primary accent: `#0066cc` (Blue)
- Text color: `#1a1a1a` (Near black)
- Secondary text: `#555` (Dark gray)
- Borders: `#e0e0e0` (Light gray)
- Backgrounds: `#f5f5f5` (Very light gray)

**Typography:**
- System font stack: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial
- Large headings: 32px, 700 weight
- Section titles: 20px, 700 weight
- Body text: 14px, 400 weight
- Metadata: 12px, 400 weight

**Responsive Design:**
- Max width: 600px (email client standard)
- Stats grid: 3 columns on desktop, responsive on mobile
- All text left-aligned for accessibility

## Environment Variables

```bash
# Marketing Agent Database
MARKETING_DB_URL=postgresql://user:pass@localhost/marketing

# Ghost CMS Integration
GHOST_URL=https://layer8.schuettken.net
GHOST_ADMIN_API_KEY=abc123:def456789

# Newsletter Settings
NEWSLETTER_PREVIEW_EMAIL=henning@example.com
NEWSLETTER_TEST_ENABLED=true
```

## Usage Examples

### Generate Monthly Newsletter

```python
from newsletter_generator import NewsletterGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

# Initialize
engine = create_async_engine("postgresql://...")
generator = NewsletterGenerator("postgresql://...")

# Generate for March 2026
async with AsyncSession(engine) as db:
    newsletter = await generator.generate_monthly_newsletter(db)
    
    print(f"Newsletter: {newsletter.month}")
    print(f"Posts: {len(newsletter.published_posts)}")
    print(f"Signals: {len(newsletter.featured_signals)}")
    print(f"Subject: {newsletter.subject_line}")
```

### Publish to Ghost

```python
from ghost_client import GhostAdminAPIClient

# Initialize with Ghost API key
ghost = GhostAdminAPIClient(
    api_key="abc123:def456789",
    ghost_url="https://layer8.schuettken.net"
)

generator = NewsletterGenerator(
    db_url="postgresql://...",
    ghost_client=ghost,
)

# Generate and publish
async with AsyncSession(engine) as db:
    newsletter = await generator.generate_monthly_newsletter(
        db,
        publish_to_ghost=True,
    )
    
    if newsletter.ghost_post_id:
        print(f"Published to Ghost: {newsletter.ghost_post_id}")
```

### API Call

```bash
# Generate newsletter for March 2026
curl -X POST http://localhost:8210/newsletters/generate \
  -H "Content-Type: application/json" \
  -d '{
    "month_date": "2026-03-15",
    "publish_to_ghost": true
  }'

# Get all newsletters
curl http://localhost:8210/newsletters

# Send to subscribers
curl -X POST http://localhost:8210/newsletters/{id}/send \
  -H "Content-Type: application/json" \
  -d '{
    "test_email": "test@example.com"
  }'
```

## Acceptance Criteria — Task 187

✅ **Monthly roundup auto-generated**
- Service aggregates posts, signals, and drafts for a calendar month
- Endpoint: `POST /newsletters/generate`
- Works with optional `month_date` parameter

✅ **Published posts included**
- Queries `marketing_blog_posts` table
- Filters by publication date and status="published"
- Displays title, excerpt, link, pillar, date in newsletter

✅ **Signals and insights included**
- Queries `marketing_signals` table
- Filters by relevance score ≥ 0.7
- Shows signal title, source, relevance score

✅ **Unpublished draft ideas included**
- Queries `marketing_drafts` table
- Shows 3 most recent ideas in "in_progress" or "awaiting_feedback" status
- Solicits subscriber feedback

✅ **Brand-consistent template**
- HTML template uses Layer 8 color scheme (#0066cc)
- Professional typography and spacing
- Email-optimized, responsive design
- Includes Layer 8 header, branding, footer

✅ **Ghost CMS integration**
- Can publish newsletter as draft post to Ghost
- Uses Ghost Admin API for creation
- Integrates with Ghost Newsletter feature for distribution

✅ **Comprehensive testing**
- 15+ unit tests covering all functions
- Tests for empty sections, data retrieval, HTML rendering
- Mocked database for isolation
- CI/CD ready

## Future Enhancements (Phase 2+)

1. **Newsletter History & Analytics**
   - Store generated newsletters in database
   - Track open/click rates from Ghost
   - Month-over-month comparison cards

2. **Content Performance Insights**
   - Add "Top Performing Posts" section
   - Highlight high-engagement signals
   - Trending topics analysis

3. **Subscriber Preference Learning**
   - Track which sections subscribers read
   - Adjust content balance based on clicks
   - A/B test subject lines

4. **Multi-Language Support**
   - Generate German version for European audience
   - Template translation framework

5. **Custom Theme Support**
   - Allow user to select newsletter theme
   - Dark mode variant
   - Custom branding options

6. **Social Media Repurposing**
   - Auto-generate Twitter threads from newsletter
   - LinkedIn carousel posts
   - Instagram story snippets

## Testing

Run the test suite:

```bash
# All newsletter tests
pytest tests/test_newsletter.py -v

# Specific test
pytest tests/test_newsletter.py::TestNewsletterGenerator::test_generate_monthly_newsletter -v

# With coverage
pytest tests/test_newsletter.py --cov=newsletter_generator
```

## Files

- `newsletter_generator.py` — Core generation logic
- `api_newsletter.py` — FastAPI endpoints
- `tests/test_newsletter.py` — Comprehensive test suite
- `NEWSLETTER_GUIDE.md` — This documentation

## Integration Points

1. **Marketing Agent Main**
   - Imported in `main.py`
   - Router registered in FastAPI app

2. **Ghost CMS**
   - Creates draft posts
   - Uses Newsletter feature for distribution
   - Analytics integration via Ghost API

3. **NATS JetStream** (future)
   - Publish `newsletter.generated` event
   - Subscribe to `signal.detected` for real-time monitoring

4. **Knowledge Graph** (future)
   - Link newsletter to related KG nodes
   - Track topic evolution

## Monitoring & Logging

The service logs all activities:

```
INFO: Generating newsletter for March 2026
INFO: Fetched 4 published posts from month
INFO: Fetched 8 featured signals
INFO: Fetched 2 draft ideas
INFO: Newsletter prepared for Ghost publication
```

Check logs:

```bash
docker logs marketing-agent | grep newsletter
```

---

**Task 187 Status:** ✅ **COMPLETE**

*Monthly roundup auto-generated from published posts + signals + unpublished insights. Template in brand style.*
