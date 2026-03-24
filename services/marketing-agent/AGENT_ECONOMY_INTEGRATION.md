# Agent Economy Integration for Marketing Agent
## Task 194: Token Budget Tracking & ROI Reporting

**Date:** 2026-03-24  
**Status:** ✅ COMPLETE  
**Assigned to:** dev-4 (Subagent)

---

## Overview

This implementation integrates the marketing-agent with the Agent Economy framework, enabling:

1. **Token Cost Tracking** — Log every LLM call with model, tokens, and cost
2. **Budget Management** — Set daily/monthly spend limits, track current usage, trigger alerts
3. **ROI Calculation** — Track cost per post + engagement metrics to compute return on investment
4. **LLM Optimization** — Recommend cheaper models for specific tasks without quality trade-offs
5. **Cost Dashboard** — Visualize spending by feature, model, and performance

---

## Architecture

### Database Schema

#### `marketing_token_costs`
Tracks every LLM call:
- `draft_id` — Links to blog post (nullable for non-post work)
- `feature` — Task type: `topic_scoring`, `draft_generation`, `image_prompt`, etc.
- `model` — Model used: `gpt-4o`, `claude-opus`, `ollama-base`, etc.
- `prompt_tokens`, `completion_tokens` — Token counts
- `cost_usd` — Calculated cost in USD
- `stage` — Content creation phase: `discovery`, `drafting`, `review`, `publishing`
- `duration_seconds` — How long the call took (for performance tracking)

#### `marketing_draft_costs`
Aggregated cost per blog post:
- `draft_id` — Links to published post
- Cost breakdown by stage: `discovery_cost_usd`, `drafting_cost_usd`, `review_cost_usd`, `publishing_cost_usd`
- `total_cost_usd` — Sum of all stages
- Engagement metrics: `actual_views`, `actual_engagement_score`
- `roi_percent` — (engagement_value - cost) / cost * 100
- `engagement_value_usd` — Estimated value of engagement (configurable per engagement unit)
- `cost_per_engagement_usd` — How much it cost to generate one engagement

#### `marketing_token_budgets`
Budget limits per workspace/marketing-agent:
- `workspace_id` — The workspace running marketing-agent
- `monthly_budget_usd`, `daily_budget_usd` — Hard limits
- `current_month_spent_usd`, `current_day_spent_usd` — Current usage
- `alert_threshold_pct` — Alert when usage > 80% of budget (configurable)
- Automatic daily/monthly reset on schedule

#### `marketing_model_optimizations`
Cost optimization recommendations:
- `feature` — e.g., `topic_scoring`
- `default_model` — Original model, e.g., `gpt-4-turbo`
- `optimized_model` — Cheaper alternative, e.g., `gpt-4o-mini`
- `cost_reduction_percent` — Estimated % savings
- `quality_trade_off` — Any quality impact (e.g., "slightly shorter summaries")
- `enabled` — Whether this optimization is active

---

## Implementation Details

### Cost Tracking Workflow

1. **Log every LLM call** — When marketing-agent calls an LLM (topic scoring, draft generation, etc.):
   ```python
   await CostTracker.log_token_usage(
       db=db,
       draft_id=draft.id,
       feature="draft_generation",
       model="gpt-4o",
       prompt_tokens=1500,
       completion_tokens=2000,
       stage="drafting",
   )
   ```

2. **Automatic cost calculation** — CostTracker uses built-in model pricing:
   - `gpt-4-turbo`: $0.01/$0.03 per 1K tokens (input/output)
   - `gpt-4o`: $0.005/$0.015 per 1K tokens
   - `claude-opus`: $0.015/$0.075 per 1K tokens
   - `ollama-base`: $0 (local LLM)

3. **Aggregate per draft** — When draft is published:
   ```python
   await CostTracker.update_draft_costs(
       db=db,
       draft_id=draft.id,
       title=draft.title,
       topic=draft.topic,
       pillar=draft.pillar,
   )
   ```

4. **Calculate ROI** — After post has been live and metrics collected:
   ```python
   await CostTracker.calculate_roi(
       db=db,
       draft_id=draft.id,
       actual_views=1250,
       engagement_score=47,  # likes + comments + shares
   )
   ```
   Result: ROI = (47 * $1.00 - $8.42) / $8.42 * 100 = **458%**

### Budget Management

The `TokenBudgetWorkspace` model tracks:
- **Monthly budget:** e.g., $500/month for all marketing work
- **Daily budget:** e.g., $20/day to avoid surprise overspends
- **Alert threshold:** Notify when usage > 80% of budget

**Automatic resets:**
- Daily spent resets at midnight (UTC)
- Monthly spent resets on the 1st of each month
- All tracked in the `month_start_date` field

**Usage check:**
```python
status = await CostTracker.check_budget_status(db, workspace_id)
# Returns:
# {
#     "daily_budget": 20.0,
#     "monthly_budget": 500.0,
#     "daily_spent": 15.37,
#     "monthly_spent": 287.42,
#     "daily_alert": False,
#     "monthly_alert": False,
# }
```

### ROI Calculation

**Formula:**
```
ROI% = (engagement_value - cost) / cost * 100
```

**Engagement value:**
- Default: $1.00 per engagement unit (like, comment, share, etc.)
- Configurable per workspace/brand

**Example:**
- Post cost: $8.42 (discovery + drafting + review + publishing)
- Views: 1,250
- Engagement: 47 (15 likes, 20 comments, 12 shares)
- Engagement value: 47 × $1.00 = $47.00
- ROI: ($47.00 - $8.42) / $8.42 × 100 = **458%**

### Model Optimization

The system can recommend cheaper models:
- **Topic Scoring:** Replace `gpt-4-turbo` ($0.01/$0.03) with `gpt-4o-mini` ($0.00015/$0.0006) → **~99% cost reduction**
- **Image Prompts:** Replace `claude-opus` with `mistral-large` → **~80% cost reduction**
- **Draft Review:** Use local `ollama-base` instead of cloud LLM → **100% cost reduction**

**Recommendations:**
```python
recommendation = await CostTracker.recommend_model_optimization(
    db=db,
    feature="topic_scoring",
    current_model="gpt-4-turbo",
)
# Returns:
# {
#     "feature": "topic_scoring",
#     "current_model": "gpt-4-turbo",
#     "optimized_model": "gpt-4o-mini",
#     "cost_reduction_percent": 98.5,
#     "quality_trade_off": "Slightly shorter summaries, but quality remains 95%",
#     "enabled": False,  # Not yet activated
# }
```

---

## API Endpoints

All endpoints require authentication (Bifrost JWT token).

### POST `/api/v1/marketing/token-usage/log`
Log a single LLM call.

**Request:**
```json
{
  "draft_id": "550e8400-e29b-41d4-a716-446655440000",
  "feature": "draft_generation",
  "model": "gpt-4o",
  "prompt_tokens": 1500,
  "completion_tokens": 2000,
  "stage": "drafting",
  "duration_seconds": 8
}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "cost_usd": 0.04275,
  "total_tokens": 3500
}
```

### POST `/api/v1/marketing/drafts/update-costs`
Aggregate costs for a draft (run when publishing).

**Request:**
```json
{
  "draft_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "SAP Datasphere Modeling Patterns",
  "topic": "SAP Datasphere",
  "pillar": "sap_technical"
}
```

**Response:**
```json
{
  "draft_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_cost_usd": 8.42,
  "discovery_cost": 1.23,
  "drafting_cost": 5.67,
  "review_cost": 0.89,
  "publishing_cost": 0.63
}
```

### POST `/api/v1/marketing/drafts/calculate-roi`
Calculate ROI after post has been live.

**Request:**
```json
{
  "draft_id": "550e8400-e29b-41d4-a716-446655440000",
  "actual_views": 1250,
  "engagement_score": 47
}
```

**Response:**
```json
{
  "draft_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_cost_usd": 8.42,
  "actual_views": 1250,
  "engagement_score": 47,
  "engagement_value_usd": 47.0,
  "roi_percent": 458.42,
  "cost_per_engagement_usd": 0.179
}
```

### GET `/api/v1/marketing/budget/status?workspace_id=<uuid>`
Check current budget usage.

**Response:**
```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ok",
  "daily_budget": 20.0,
  "monthly_budget": 500.0,
  "daily_spent": 15.37,
  "monthly_spent": 287.42,
  "daily_alert": false,
  "monthly_alert": false
}
```

### GET `/api/v1/marketing/cost-dashboard?workspace_id=<uuid>&days=30`
Get comprehensive cost dashboard.

**Response:**
```json
{
  "period_days": 30,
  "cost_by_feature": [
    {"feature": "draft_generation", "cost": 125.43, "calls": 45},
    {"feature": "topic_scoring", "cost": 32.18, "calls": 340},
    {"feature": "image_prompt", "cost": 18.75, "calls": 25}
  ],
  "cost_by_model": [
    {"model": "gpt-4o", "cost": 102.34, "calls": 120},
    {"model": "gpt-4o-mini", "cost": 32.18, "calls": 340},
    {"model": "claude-opus", "cost": 41.84, "calls": 50}
  ],
  "post_statistics": {
    "posts_published": 8,
    "total_cost": 176.36,
    "avg_roi_percent": 342.5,
    "avg_engagement_value": 58.75
  },
  "budget_status": {
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "ok",
    "daily_budget": 20.0,
    "monthly_budget": 500.0,
    "daily_spent": 15.37,
    "monthly_spent": 287.42,
    "daily_alert": false,
    "monthly_alert": false
  }
}
```

### GET `/api/v1/marketing/model-optimization/recommend?feature=<str>&current_model=<str>`
Get model optimization recommendation.

**Response:**
```json
{
  "feature": "topic_scoring",
  "current_model": "gpt-4-turbo",
  "optimized_model": "gpt-4o-mini",
  "cost_reduction_percent": 98.5,
  "quality_trade_off": "Slightly shorter summaries, but quality remains 95%",
  "enabled": false
}
```

### POST `/api/v1/marketing/cost-analysis?workspace_id=<uuid>`
Generate comprehensive cost analysis with recommendations.

**Response:**
```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "analysis_date": "2026-03-24",
  "dashboard": { ... },
  "recommendations": [
    {
      "type": "high_cost_feature",
      "feature": "draft_generation",
      "current_cost": 125.43,
      "suggestion": "Consider using a cheaper model for draft_generation"
    },
    {
      "type": "low_roi",
      "avg_roi": -12.5,
      "suggestion": "Recent posts have low ROI. Review content strategy and engagement metrics."
    }
  ],
  "summary": {
    "total_cost_30d": 176.36,
    "posts_published": 8,
    "avg_cost_per_post": 22.04
  }
}
```

---

## Integration with Marketing-Agent

### Step 1: Add Cost Logging to Draft Generation

In `services/marketing-agent/app/services/draft_generation.py`:

```python
from cost_tracking import CostTracker

async def generate_draft(
    db: AsyncSession,
    topic: str,
    audience: str,
    tone: str,
):
    """Generate a blog draft with cost tracking."""
    draft_id = uuid4()
    
    # Call LLM for draft generation
    response = await call_llm(
        model="gpt-4o",
        prompt=f"Write a blog post about {topic}...",
    )
    
    # Log the cost
    await CostTracker.log_token_usage(
        db=db,
        draft_id=draft_id,
        feature="draft_generation",
        model="gpt-4o",
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        stage="drafting",
    )
    
    return draft_id
```

### Step 2: Aggregate Costs When Publishing

In `services/marketing-agent/app/services/publishing.py`:

```python
async def publish_to_ghost(
    db: AsyncSession,
    draft_id: UUID,
    draft_title: str,
):
    """Publish draft to Ghost CMS."""
    # ... existing publishing code ...
    
    # Aggregate costs
    summary = await CostTracker.update_draft_costs(
        db=db,
        draft_id=draft_id,
        title=draft_title,
        topic=draft_topic,
        pillar=draft_pillar,
    )
    
    logger.info(f"Published draft {draft_id} with total cost ${summary.total_cost_usd}")
    
    # Publish to Ghost
    ghost_post_id = await ghost_client.create_post(...)
    
    # Update cost summary with published date
    summary.published_at = datetime.utcnow()
    await db.commit()
    
    return ghost_post_id
```

### Step 3: Track Engagement and Calculate ROI

In `services/marketing-agent/app/services/analytics.py`:

```python
async def sync_analytics(
    db: AsyncSession,
    draft_id: UUID,
):
    """Sync engagement metrics and calculate ROI."""
    # Get views from Ghost or analytics API
    views = await ghost_client.get_post_views(draft_id)
    engagement = await ghost_client.get_post_engagement(draft_id)
    
    # Calculate ROI
    summary = await CostTracker.calculate_roi(
        db=db,
        draft_id=draft_id,
        actual_views=views,
        engagement_score=engagement,
    )
    
    logger.info(f"Post {draft_id} ROI: {summary.roi_percent}%")
    
    # Publish ROI event for dashboard
    await nats.publish(
        subject="marketing.post.roi_calculated",
        data={
            "draft_id": str(draft_id),
            "roi_percent": summary.roi_percent,
            "total_cost": float(summary.total_cost_usd),
        },
    )
```

---

## Configuration

### Model Pricing

Edit `cost_tracking.py` `MODEL_PRICES` dict to update pricing:

```python
MODEL_PRICES = {
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    # Add new models here
}
```

### Engagement Value

By default, $1.00 per engagement unit. Adjust in `calculate_roi()`:

```python
# $1.50 per engagement unit (more conservative)
engagement_value = Decimal(str(float(engagement_score) * 1.5))
```

### Budget Limits

Set budget limits for a workspace:

```python
# In database or via API
budget = TokenBudgetWorkspace(
    workspace_id=workspace_id,
    monthly_budget_usd=Decimal("500"),
    daily_budget_usd=Decimal("20"),
    alert_threshold_pct=0.8,
)
db.add(budget)
await db.commit()
```

---

## Monitoring & Alerts

The cost tracking system integrates with the Agent Economy:

### Daily Budget Alert
When daily spending reaches 80% of daily budget:
```
📊 Daily marketing spend approaching limit
Current: $16.00 / Daily budget: $20.00 (80%)
```

### Monthly Budget Alert
When monthly spending reaches 80% of monthly budget:
```
📊 Monthly marketing spend approaching limit
Current: $400.00 / Monthly budget: $500.00 (80%)
```

### Low ROI Alert
When a post ROI drops below -50%:
```
⚠️ Post "SAP Datasphere Modeling" has low ROI (-67%)
Consider reviewing content strategy or engagement metrics
```

---

## Files Modified/Created

### New Files
- `models_cost_tracking.py` — Database models
- `cost_tracking.py` — Cost tracking and ROI calculation service
- `api_cost_tracking.py` — FastAPI endpoints
- `migrations/001_agent_economy_cost_tracking.py` — Database migration
- `AGENT_ECONOMY_INTEGRATION.md` — This documentation

### Integration Points
- `main.py` — Include cost tracking router
- `ghost_client.py` — Add engagement metrics sync
- Marketing-agent draft generation services — Log token usage
- Marketing-agent publishing service — Aggregate costs and calculate ROI

---

## Deployment

1. **Database migration:**
   ```bash
   alembic upgrade head
   ```

2. **Install/update dependencies:**
   ```bash
   pip install sqlalchemy fastapi pydantic
   ```

3. **Integrate into main.py:**
   ```python
   from api_cost_tracking import router as cost_router
   
   app.include_router(cost_router)
   ```

4. **Set environment variables:**
   ```bash
   MARKETING_WORKSPACE_ID=<uuid>
   MARKETING_MONTHLY_BUDGET=500
   MARKETING_DAILY_BUDGET=20
   MARKETING_ALERT_THRESHOLD=0.8
   ```

5. **Start the service:**
   ```bash
   docker-compose up marketing-agent
   ```

---

## Acceptance Criteria ✅

- [x] Token cost tracking for every LLM call
- [x] Cost aggregation by content stage (discovery/drafting/review/publishing)
- [x] ROI calculation (cost vs engagement value)
- [x] Budget tracking with daily/monthly limits
- [x] Alert system when approaching budget limits
- [x] Model optimization recommendations
- [x] Cost dashboard with feature/model breakdown
- [x] API endpoints for all operations
- [x] Database migrations
- [x] Complete documentation

---

## Future Enhancements

- **Predictive budgeting:** ML model to forecast monthly spend based on content velocity
- **Cost variance analysis:** Why did this post cost 50% more than similar posts?
- **A/B testing cost:** Track cost of two draft versions to optimize for ROI
- **Multi-tenant budgeting:** Different budgets per workspace/brand
- **Cost attribution:** Trace costs back to contributing factors (model choice, length, complexity)

---

**Status:** ✅ Task 194 Complete and Ready for Integration  
**Committed:** Yes  
**Deployed:** Ready for docker-compose deployment via ops-bridge  
**QA:** All acceptance criteria met
