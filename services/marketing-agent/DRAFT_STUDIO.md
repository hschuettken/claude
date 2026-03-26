# Draft Studio API — Task #167

## Overview

**Draft Studio** is a split-pane web editor for marketing content drafts with integrated governance checks, Knowledge Graph context, and style/compliance validation. It enables content creators to write, review, and iterate on drafts with real-time feedback on compliance and readability.

**Task:** #167 — Draft Studio  
**Status:** ✅ Complete  
**Endpoints:** `/api/v1/draft-studio/*`  
**Repository:** `/home/hesch/.openclaw/workspace-nb9os/claude/` (Gitea: `atlas/claude`)

---

## Architecture

Draft Studio consists of three synchronized panes:

### 1. **Left Pane — Sources, KG Context & Citations**
- **Signals**: Source drafts from detected marketing signals
- **Topics**: Link to content strategy topics
- **Knowledge Graph Context**: 
  - Previously published posts on related topics
  - Active projects and tasks
  - Content pillar statistics
- **Citations**: User-added sources with relevance scoring

### 2. **Center Pane — Rich Text Editor**
- Live editing of draft content (HTML/Markdown)
- Auto-saving to database
- Metadata: title, summary, tags, SEO fields
- Word count and reading time estimation
- Platform selection (blog, LinkedIn, email, Twitter)

### 3. **Right Pane — Style Checks, Risk Flags & CTAs**
- **Governance Risk Flags**: 
  - Client references (e.g., "Lindt", "Horváth")
  - Unverified metrics ("45% increase")
  - Roadmap claims ("will release")
  - Confidentiality risks (blocks publishing if critical)
  - Unverified feature claims
  - Unsubstantiated comparisons
- **Readability Score**: Flesch-Kincaid-style calculation (0-100)
- **CTA Variants**: AI-generated call-to-action button options
- **Visual Prompt**: Suggested hero image keywords
- **Governance Summary**: Human-readable risk report

---

## API Endpoints

### Open Draft in Studio
```
POST /api/v1/draft-studio/open
Query: draft_id (int)
Response: DraftStudioState (all 3 panes)
```

Returns complete three-pane state for a draft, including Knowledge Graph context and governance analysis.

**Example Request:**
```bash
curl -X POST http://localhost:8210/api/v1/draft-studio/open?draft_id=42
```

**Example Response:**
```json
{
  "draft_id": 42,
  "left_pane": {
    "signal_id": 10,
    "topic_id": 5,
    "citations": [
      {
        "title": "Signal: SAP Datasphere Trends",
        "url": "...",
        "source": "signal",
        "relevance": 0.8
      }
    ],
    "kg_context": [
      {
        "type": "published_post",
        "title": "Datasphere Setup Guide",
        "metadata": {...}
      }
    ]
  },
  "center_pane": {
    "id": 42,
    "title": "Datasphere Data Governance",
    "content": "...",
    "word_count": 1250,
    "last_saved_at": "2025-03-26T12:00:00Z"
  },
  "right_pane": {
    "risk_flags": [
      {
        "type": "client_reference",
        "match": "Lindt",
        "line_number": 15,
        "action": "review",
        "remediation": "Replace with generic company reference"
      }
    ],
    "readability_score": 72.5,
    "estimated_reading_time": 6,
    "cta_variants": [
      {
        "id": "cta_0",
        "text": "Learn more",
        "style": "button",
        "confidence": 0.8
      }
    ],
    "governance_blocks": false,
    "governance_summary": "Found 2 risk flag(s): ..."
  }
}
```

---

### Update Center Pane (Editor Content)
```
PUT /api/v1/draft-studio/{draft_id}/center
Body: DraftEditorData
Response: DraftEditorData (updated)
```

Auto-saves draft content, title, metadata, and tags.

**Example Request:**
```bash
curl -X PUT http://localhost:8210/api/v1/draft-studio/42/center \
  -H "Content-Type: application/json" \
  -d '{
    "id": 42,
    "title": "Updated Title",
    "content": "Updated content...",
    "tags": ["updated", "sap"],
    "seo_title": "SEO Title",
    "word_count": 1500
  }'
```

---

### Get/Refresh Right Pane
```
GET /api/v1/draft-studio/{draft_id}/right
Response: RightPaneChecks (governance checks, readability, CTAs)
```

Re-scans governance and regenerates style/readability checks on demand.

**Example Request:**
```bash
curl http://localhost:8210/api/v1/draft-studio/42/right
```

---

### Add Citation
```
POST /api/v1/draft-studio/{draft_id}/citations
Body: Citation
Response: Citation (with added_at timestamp)
```

Add a source citation to the left pane (signal, topic, research URL, etc.).

**Example Request:**
```bash
curl -X POST http://localhost:8210/api/v1/draft-studio/42/citations \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Gartner Magic Quadrant",
    "url": "https://example.com/gartner",
    "source": "research",
    "relevance": 0.95,
    "snippet": "Leading in data governance..."
  }'
```

---

### Delete Citation
```
DELETE /api/v1/draft-studio/{draft_id}/citations/{citation_index}
Response: {status: "ok", deleted_index: int}
```

Remove a citation by index from the citations list.

---

## Data Models

### DraftStudioState
Complete state for Draft Studio, combining all three panes:

```python
class DraftStudioState(BaseModel):
    draft_id: int
    left_pane: LeftPaneContext
    center_pane: DraftEditorData
    right_pane: RightPaneChecks
    created_at: str
    updated_at: str
```

### LeftPaneContext
Sources, KG context, and citations:

```python
class LeftPaneContext(BaseModel):
    signal_id: Optional[int] = None
    signal: Optional[Dict[str, Any]] = None
    topic_id: Optional[int] = None
    topic: Optional[Dict[str, Any]] = None
    kg_context: List[KGContextItem] = []
    citations: List[Citation] = []
    pillar_id: Optional[int] = None
```

### DraftEditorData
Rich text editor content and metadata:

```python
class DraftEditorData(BaseModel):
    id: int
    title: str
    content: str  # HTML or Markdown
    summary: Optional[str] = None
    platform: str = "blog"  # blog, linkedin, twitter, email
    tags: List[str] = []
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    status: str = "draft"
    word_count: int = 0
    last_saved_at: Optional[str] = None
```

### RightPaneChecks
Governance flags, style checks, readability, CTAs:

```python
class RightPaneChecks(BaseModel):
    style_checks: List[StyleCheck] = []
    risk_flags: List[RiskFlagWithSuggestion] = []
    readability_score: float  # 0-100
    estimated_reading_time: int  # minutes
    visual_prompt: Optional[str] = None
    cta_variants: List[CTAVariant] = []
    governance_blocks: bool = False  # Critical risks block publishing
    governance_summary: str  # Human-readable risk report
```

### RiskFlagWithSuggestion
Governance risk flag with remediation:

```python
class RiskFlagWithSuggestion(BaseModel):
    type: str  # client_reference, unverified_metric, roadmap_claim, ...
    match: str  # The matched text
    line_number: int
    action: str  # "review" or "block"
    remediation: Optional[str] = None  # How to fix it
```

### Citation
Source reference with relevance scoring:

```python
class Citation(BaseModel):
    id: Optional[int] = None
    title: str
    url: str
    source: str  # signal, topic, research, post, ...
    relevance: float  # 0.0-1.0 confidence
    snippet: Optional[str] = None
    added_at: Optional[str] = None
```

### CTAVariant
Call-to-action variant for A/B testing:

```python
class CTAVariant(BaseModel):
    id: str
    text: str
    color: str = "blue"
    style: str = "button"  # button, link, text
    position: str = "end"  # start, end, middle
    confidence: float  # 0.0-1.0 AI confidence
```

---

## Governance Risk Detection

Draft Studio integrates the **Governance Scanner** from `app/drafts/governance.py`. It detects:

### Risk Types
| Type | Pattern | Action | Remediation |
|------|---------|--------|-------------|
| `client_reference` | Client names (Lindt, Horváth) | Review | Remove or genericize |
| `unverified_metric` | Claims with %/$ (45% increase) | Review | Add citation/source |
| `roadmap_claim` | Future tense (will release, planned) | Review | Reframe as potential |
| `confidentiality_risk` | Confidential, NDA, secret | **Block** | Remove entirely |
| `unverified_feature` | SAP feature claims without proof | Review | Link to docs |
| `unsubstantiated_claim` | Comparative claims (better than, fastest) | Review | Add evidence |
| `style_allcaps` | ALL_CAPS emphasis | Review | Use markdown emphasis |

### Blocking vs. Review
- **Blocking** (`action: "block"`): Confidentiality risks prevent publishing (`governance_blocks: true`)
- **Review** (`action: "review"`): Warnings for human review, don't block publishing

### Example: Flag Detection
```
Draft content: "Lindt is seeing 200% improvement with Datasphere."

Detected flags:
1. client_reference: "Lindt" → Remediation: "Replace with generic"
2. unverified_metric: "200% improvement" → Remediation: "Add citation"
```

---

## Knowledge Graph Integration

Draft Studio enriches drafts with Knowledge Graph context:

### KG Context Types
| Type | Source | Purpose |
|------|--------|---------|
| `published_post` | Neo4j Post nodes | Related previously-published content |
| `active_project` | Neo4j Project nodes | Relevant ongoing work/tasks |
| `pillar_stat` | Content pillar analytics | Content distribution stats (1-6 pillars) |

### KG Availability Check
If Knowledge Graph is unavailable (Neo4j down, connection failed), Draft Studio gracefully degrades:
- Left pane: Shows signal/topic, skips KG context
- Right pane: Still performs governance checks
- No breaking errors

---

## Readability & Metrics

### Readability Score
Simplified Flesch-Kincaid style (0-100):
- **~15 words/sentence**: Ideal score (100)
- **<5 words/sentence**: Too fragmented
- **>25 words/sentence**: Too complex

Calculation:
```
score = max(0, min(100, 100 - (|avg_sentence_length - 15| * 2)))
```

### Estimated Reading Time
```
reading_time = ceil(word_count / 200)  # ~200 words/min
```

### CTA Variants
Auto-generated 3-5 call-to-action variants with confidence scores:
- "Learn more" (button, 0.7)
- "Explore the full guide" (link, 0.8)
- "Get started now" (button, 0.9)

---

## Usage Example (Frontend Integration)

### Load Draft
```javascript
async function openDraft(draftId) {
  const response = await fetch(`/api/v1/draft-studio/open?draft_id=${draftId}`);
  const state = await response.json();
  
  // Populate three panes
  renderLeftPane(state.left_pane);
  renderCenterPane(state.center_pane);
  renderRightPane(state.right_pane);
}
```

### Save Content
```javascript
async function saveContent(draftId, editorData) {
  const response = await fetch(`/api/v1/draft-studio/${draftId}/center`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(editorData)
  });
  return await response.json();
}
```

### Add Citation
```javascript
async function addCitation(draftId, citation) {
  const response = await fetch(`/api/v1/draft-studio/${draftId}/citations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(citation)
  });
  return await response.json();
}
```

### Refresh Risk Checks
```javascript
async function refreshRightPane(draftId) {
  const response = await fetch(`/api/v1/draft-studio/${draftId}/right`);
  return await response.json();
}
```

---

## Testing

Run Draft Studio tests:
```bash
cd services/marketing-agent
python3 -m pytest tests/test_draft_studio.py -v
```

**Tests:** 17 comprehensive tests covering:
- API structure and endpoints
- Data model validation
- Governance risk detection
- KG integration
- Database operations
- Error handling
- Readability calculation
- CTA variant generation

**Test Results:**
```
17 passed in 0.06s
```

---

## File Structure

```
services/marketing-agent/
├── api/
│   ├── draft_studio.py          ← Main Draft Studio API (576 lines)
│   └── __init__.py              ← Router export
├── main.py                      ← Router registration
├── tests/
│   └── test_draft_studio.py     ← 17 tests (all passing)
├── DRAFT_STUDIO.md              ← This file
└── ...
```

---

## Commit History

| Commit | Message |
|--------|---------|
| `d84fd7b` | feat(draft-studio): split-pane draft editor #167 |
| `41b2246` | test(draft-studio): comprehensive test suite for Draft Studio API |

---

## Future Enhancements

### Planned
1. **AI-Powered Content Suggestions**: Auto-generate headline variants, improve weak sentences
2. **Citation Linking**: Link citations directly to content (in-draft anchors)
3. **Collaboration**: Real-time multi-user editing with locking/conflict resolution
4. **Analytics Integration**: Show post performance metrics in editor
5. **Custom Governance Rules**: Per-client or per-project risk patterns
6. **Tone Analysis**: Brand voice consistency checking

### Integration Points
- **Newsletter Generator**: Use saved drafts for newsletter compilation
- **Scout Engine**: Auto-link detected signals as citations
- **Publishing Pipeline**: One-click publish to Ghost CMS
- **Content Calendar**: Visual timeline of scheduled drafts

---

## Technical Notes

### Dependencies
- FastAPI (async HTTP)
- SQLAlchemy (async ORM)
- Neo4j (Knowledge Graph, optional)
- Pydantic (data validation)

### Performance
- **Governance scanning**: O(n) line scans with regex patterns
- **KG queries**: Async, non-blocking; graceful degradation if unavailable
- **Database**: Single-session per request, transactional

### Security
- Input validation via Pydantic
- SQL injection prevention via parameterized queries
- Error messages don't leak internals
- No direct Neo4j/DB credentials exposed in API

---

## Support & Questions

For issues, PRs, or feature requests:
- **Repository**: http://192.168.0.64:3000/atlas/claude.git
- **Branch**: `main` (or `master`)
- **Issues**: Tracked in Orbit task #167

---

_Draft Studio API Implementation — Task #167_  
_Last updated: 2025-03-26_
