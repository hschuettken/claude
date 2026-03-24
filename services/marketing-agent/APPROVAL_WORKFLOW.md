# Approval Workflow Implementation (Task 162)

## Overview

Complete approval state machine for marketing drafts with status visibility, notifications, and timeline history tracking.

## Architecture

### Status States

```
draft → review → approved → scheduled → published
         ↓ (reject)
       draft (with feedback)
```

- **draft**: Initial state, author editing
- **review**: Awaiting Henning's review, Orbit task created, Discord notified
- **approved**: Ready to publish, can schedule or publish immediately
- **scheduled**: Scheduled for automatic publication
- **published**: Live on Ghost
- **rejected**: Returned to draft with feedback (not a terminal state)

### Database Schema

#### `marketing.drafts` (updated)
- `rejection_feedback TEXT` — Feedback when rejected during review

#### `marketing.status_history` (new)
- `id SERIAL PRIMARY KEY`
- `draft_id INTEGER FK` — Links to draft
- `from_status VARCHAR(50)` — Previous status (NULL for initial)
- `to_status VARCHAR(50)` — New status
- `changed_by VARCHAR(255)` — User who made change
- `feedback TEXT` — Rejection feedback or notes
- `created_at TIMESTAMPTZ` — When transition occurred
- Indexes: draft_id, created_at, to_status

#### `marketing.approval_queue` (new)
- `id SERIAL PRIMARY KEY`
- `draft_id INTEGER FK UNIQUE` — Which draft is pending
- `queued_at TIMESTAMPTZ` — When submitted for review
- `assigned_to VARCHAR(255)` — Reviewer (e.g., "henning")
- `orbit_task_id VARCHAR(255)` — Link to Orbit task
- `discord_notified_at TIMESTAMPTZ` — When Discord notification sent
- Indexes: queued_at, assigned_to, orbit_task_id

## API Endpoints

### Status Transitions

#### `POST /api/v1/marketing/drafts/{id}/review`
Submit draft for review (draft → review)
```json
{
  "changed_by": "system",
  "feedback": null
}
```
**Effects:**
- Status: draft → review
- Creates `StatusHistory` entry
- Creates `ApprovalQueue` entry
- Creates Orbit task: "Draft pending review: [title]"
- Sends Discord notification: "@henning Draft ready for review: [link]"
- Returns updated draft with status history

#### `POST /api/v1/marketing/drafts/{id}/approve`
Approve a draft (review → approved)
```json
{
  "changed_by": "henning",
  "feedback": null
}
```
**Effects:**
- Status: review → approved
- Removes from `ApprovalQueue`
- Sends Discord notification

#### `POST /api/v1/marketing/drafts/{id}/reject`
Reject draft with feedback (review → draft)
```json
{
  "changed_by": "henning",
  "feedback": "Please clarify the introduction"
}
```
**Effects:**
- Status: review → draft
- Stores rejection feedback in `draft.rejection_feedback`
- Removes from `ApprovalQueue`
- Sends Discord notification
- **Note:** Rejection is optional feedback; rejecting is a way to send feedback AND return to draft for editing

#### `PATCH /api/v1/marketing/drafts/{id}/status`
Generic state transition (validates against rules)
```json
{
  "to_status": "approved",
  "changed_by": "system",
  "feedback": null
}
```

### Filtering & Visibility

#### `GET /api/v1/marketing/drafts?status=review`
List drafts filtered by status
- Query param: `status=draft|review|approved|scheduled|published|rejected`
- Returns all drafts with full status history

#### `GET /api/v1/marketing/drafts/{id}/history`
Get full timeline of status transitions for a draft
```json
[
  {
    "id": 1,
    "from_status": null,
    "to_status": "draft",
    "changed_by": "system",
    "feedback": null,
    "created_at": "2025-03-24T10:00:00Z"
  },
  {
    "id": 2,
    "from_status": "draft",
    "to_status": "review",
    "changed_by": "author",
    "feedback": null,
    "created_at": "2025-03-24T11:00:00Z"
  },
  {
    "id": 3,
    "from_status": "review",
    "to_status": "approved",
    "changed_by": "henning",
    "feedback": null,
    "created_at": "2025-03-24T11:30:00Z"
  }
]
```

#### `GET /api/v1/marketing/stats/approval`
Dashboard statistics
```json
{
  "pending_review_count": 3,
  "approved_count": 5,
  "rejected_count": 2,
  "scheduled_count": 1,
  "published_count": 42
}
```

## Frontend Integration

### Types (`src/types/marketing.ts`)
- Added `StatusHistoryEntry` interface
- Updated `Draft` interface:
  - `status`: Added `scheduled` and `rejected`
  - `rejection_feedback?: string`
  - `status_history?: StatusHistoryEntry[]`

### API Client (`src/lib/api/marketing.ts`)
New methods:
- `submitForReview(id, changedBy)` — Submit for review
- `approve(id, changedBy)` — Approve draft
- `reject(id, feedback, changedBy)` — Reject with feedback
- `getStatusHistory(id)` — Get full status timeline
- `getApprovalStats()` — Get approval stats

### Draft Detail Page (`src/pages/marketing/DraftDetailPage.tsx`)
- Status display with color coding (new: purple for scheduled, red for rejected)
- Rejection feedback display when present
- Approval actions (when in review state):
  - ✅ Approve button
  - ❌ Reject button (with feedback modal)
- Submit for review button (when in draft state)
- Status history timeline (collapsible):
  - Shows all transitions with timestamps
  - Displays who made each change
  - Shows rejection feedback

## Notifications

### Orbit Task
When draft submitted for review:
```json
{
  "title": "Draft pending review: [draft_title]",
  "description": "Marketing draft #123 awaiting approval",
  "status": "open",
  "priority": "high",
  "tags": ["marketing", "review"],
  "metadata": {
    "draft_id": 123,
    "type": "approval"
  }
}
```

### Discord
Emitted via NATS event (consumed by Discord bot):
```json
{
  "event": "draft.status_changed",
  "draft_id": 123,
  "title": "New Product Announcement",
  "status": "review",
  "timestamp": "2025-03-24T11:00:00Z"
}
```

Bot should format as:
- **review**: "@henning Draft ready for review: New Product Announcement [link]"
- **approved**: "✅ Draft approved: New Product Announcement"
- **rejected**: "❌ Draft rejected for revision: New Product Announcement"

### Dashboard Badge
Approval queue count queried via `/api/v1/marketing/stats/approval`
- Shows `pending_review_count` in NB9OS dashboard
- Updates in real-time as drafts enter/exit review state

## State Transition Validation Rules

```python
ALLOWED_TRANSITIONS = {
    DraftStatus.draft: [DraftStatus.review],
    DraftStatus.review: [DraftStatus.approved, DraftStatus.draft],  # reject returns to draft
    DraftStatus.approved: [DraftStatus.scheduled, DraftStatus.published],
    DraftStatus.scheduled: [DraftStatus.published],
    DraftStatus.published: [DraftStatus.draft],  # Re-editing published posts
    DraftStatus.archived: [],  # Terminal state
}
```

### Validation Rules
- Rejection requires feedback text (not null/empty)
- Transitions must follow the state machine (no invalid paths)
- Status history records all transitions with author & timestamp
- Approval queue automatically manages review assignments

## Migration Steps

1. Run `migrations/002_approval_workflow.sql` to create:
   - `status_history` table
   - `approval_queue` table
   - Seed initial status history from existing drafts

2. Update models in `models.py`:
   - Add `StatusHistory` and `ApprovalQueue` SQLAlchemy models
   - Add relationships to `Draft` model

3. Add approval API endpoints in `api/approval.py`:
   - Status transition endpoints
   - Filtering by status
   - History retrieval
   - Statistics

4. Update main.py to include approval router

5. Run frontend updates:
   - Update types in `src/types/marketing.ts`
   - Add API client methods in `src/lib/api/marketing.ts`
   - Update draft detail page with approval UI

## Testing Checklist

- [ ] Status enum working in database
- [ ] Transition validation (invalid paths rejected)
- [ ] Orbit task created when draft submitted for review
- [ ] Discord notification sent via NATS event
- [ ] Status history visible in draft detail (with timestamps)
- [ ] Rejection feedback stored and displayed
- [ ] Approval queue tracks pending drafts
- [ ] Dashboard stats show pending count
- [ ] Status filtering works (GET /api/v1/marketing/drafts?status=review)
- [ ] Approval workflow buttons appear in correct states
- [ ] Rejection feedback modal works
- [ ] Status history timeline displays correctly

## Estimated Timeline

- Database setup: 10 min
- API implementation: 30 min
- Frontend UI: 20 min
- Notification integration: 15 min (depends on Orbit & Discord bot)
- Testing: 15 min
- **Total: ~90 minutes**

This is critical for content workflow and blocks on Henning's approval process for all marketing drafts.
