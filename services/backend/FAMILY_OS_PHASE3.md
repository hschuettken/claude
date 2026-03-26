# Family OS Phase 3: Shared Decisions

_Couple voting, decision history, and conflict resolution suggestions_

## Overview

Family OS Phase 3 extends the household decision-making system with:

1. **Couple Voting** — Binary (yes/no) and ranked-choice voting
2. **Decision History** — Archive of resolved decisions with outcomes and lessons learned
3. **Conflict Resolution** — AI-driven or rule-based suggestions for resolving disagreements

## Architecture

### Components

- **family_os_models.py** — Pydantic models for all request/response types
- **family_os_service.py** — Core business logic for decisions, votes, history
- **family_os_routes.py** — FastAPI endpoints for REST API
- **test_family_os.py** — Comprehensive test suite (pytest)
- **migrations/001_family_os_phase3.sql** — PostgreSQL schema

### Database Schema

```
family_os.users
├─ id (UUID)
├─ household_id (UUID)
├─ name (text)
├─ email (text)
├─ role (text)
└─ preferences (JSONB)

family_os.decisions
├─ id (UUID)
├─ household_id (UUID)
├─ title (text)
├─ description (text)
├─ category (text)
├─ status (open|resolved|archived)
├─ voting_method (binary|ranked_choice|weighted)
├─ options (array)
├─ created_by (UUID)
├─ created_at (timestamp)
├─ deadline (timestamp)
├─ resolved_at (timestamp)
├─ final_outcome (text)
└─ resolution_notes (text)

family_os.votes
├─ id (UUID)
├─ decision_id (UUID)
├─ voter_id (UUID)
├─ vote_value (text)
├─ rationale (text)
├─ confidence (numeric 0-1)
└─ created_at (timestamp)

family_os.decision_history
├─ id (UUID)
├─ household_id (UUID)
├─ decision_id (UUID)
├─ original_title (text)
├─ voting_summary (JSONB)
├─ final_outcome (text)
├─ resolution_method (consensus|majority|weighted|discussion|compromise)
├─ impact_assessment (text)
├─ learned_lessons (array)
└─ resolved_at (timestamp)

family_os.conflict_resolutions
├─ id (UUID)
├─ decision_id (UUID)
├─ conflict_type (disagreement|stalemate|competing_values|resource_constraint)
├─ severity (numeric 1-10)
├─ user1_position (text)
├─ user2_position (text)
├─ suggested_resolution (JSONB)
├─ source (ai_generated|rule_based|manual)
├─ accepted (boolean)
└─ created_at (timestamp)
```

## API Endpoints

### Decisions

```http
POST   /api/v1/family-os/decisions
GET    /api/v1/family-os/decisions/{decision_id}
GET    /api/v1/family-os/households/{household_id}/decisions?status=open&limit=20
POST   /api/v1/family-os/decisions/{decision_id}/resolve
```

### Voting

```http
POST   /api/v1/family-os/decisions/{decision_id}/votes
GET    /api/v1/family-os/decisions/{decision_id}/votes
```

### History

```http
POST   /api/v1/family-os/households/{household_id}/history
GET    /api/v1/family-os/households/{household_id}/history
```

### Conflict Resolution

```http
GET    /api/v1/family-os/decisions/{decision_id}/conflict
POST   /api/v1/family-os/decisions/{decision_id}/resolve-conflict
```

### Statistics

```http
GET    /api/v1/family-os/households/{household_id}/stats
```

## Usage Examples

### Create a Decision

```python
from family_os_models import DecisionCreateRequest, VotingMethod

request = DecisionCreateRequest(
    title="Should we renovate the kitchen?",
    description="The kitchen is outdated and inefficient",
    category="home",
    voting_method=VotingMethod.BINARY,
    deadline=datetime.utcnow() + timedelta(days=7),
)

decision = await service.create_decision(
    household_id=UUID("..."),
    user_id=UUID("..."),
    request=request,
)
```

### Cast a Vote

```python
from family_os_models import VoteCreateRequest

vote = VoteCreateRequest(
    vote_value="yes",
    rationale="The kitchen needs better lighting and workflow",
    confidence=0.85,
)

result = await service.cast_vote(
    decision_id=UUID("..."),
    voter_id=UUID("..."),
    request=vote,
)
```

### Detect Conflicts

```python
conflict = await service.detect_conflict(decision_id=UUID("..."))

if conflict:
    print(f"Conflict detected: {conflict['conflict_type']}")
    print(f"Severity: {conflict['severity']}/10")
```

### Get Resolution Suggestions

```python
resolutions = await service.generate_conflict_resolution(
    decision_id=UUID("..."),
    conflict_type=ConflictType.DISAGREEMENT,
    additional_context="We have budget constraints",
)

for suggestion in resolutions["suggestions"]:
    print(f"- {suggestion['type']}: {suggestion['details']}")
    print(f"  Likelihood: {suggestion['likelihood']}")
```

### Resolve and Archive

```python
# Resolve the decision
resolved = await service.resolve_decision(
    decision_id=UUID("..."),
    outcome="We'll renovate starting next month",
    method=ResolutionMethod.COMPROMISE,
    notes="Split the difference - kitchen only, not dining room",
)

# Archive to history with lessons
history = await service.archive_decision(
    household_id=UUID("..."),
    request=DecisionHistoryCreateRequest(
        decision_id=UUID("..."),
        resolution_method=ResolutionMethod.COMPROMISE,
        impact_assessment="Good compromise, both happy with kitchen",
        learned_lessons=[
            "Compromise works better than winner-take-all",
            "Setting a timeline helps get buy-in",
            "Budget discussion earlier would help",
        ],
    ),
)
```

## Voting Methods

### Binary Voting
Simple yes/no or agree/disagree. Used for simple decisions.

```python
options=["Yes", "No"]
vote_value="yes"
```

### Ranked Choice
Rank multiple options by preference. Used for decisions with 3+ alternatives.

```python
options=["Italy", "Spain", "Portugal", "Greece"]
vote_value="1st_choice:Italy, 2nd_choice:Spain"
```

### Weighted Voting
Votes weighted by confidence level. More confident voters have more influence.

```python
vote_value="yes"
confidence=0.95  # High confidence = more weight
```

## Conflict Types

- **Disagreement** — Different preferences (e.g., "yes" vs "no")
- **Stalemate** — Tied votes, no winner
- **Competing Values** — Different underlying values (e.g., sustainability vs. cost)
- **Resource Constraint** — Both want something incompatible with budget/time

## Resolution Methods

- **Consensus** — Both agree (best outcome)
- **Majority** — One person's preference wins (50% satisfaction)
- **Weighted Vote** — Vote weighted by confidence
- **Discussion** — Talked it through, found common ground
- **Compromise** — Hybrid solution where both give up something

## Conflict Resolution Strategies

### Rule-Based (Default)

For **Disagreement**:
1. Find shared goal underneath the different preferences
2. Propose hybrid solution combining elements from both

For **Stalemate**:
1. Structured discussion (10 min uninterrupted per person)
2. Trial period (pick one option, test for 2 weeks)

### AI-Driven (Optional)

With LLM integration, system can:
- Understand nuanced positions beyond yes/no
- Suggest creative third options
- Identify hidden concerns
- Predict likelihood of each resolution approach

## Testing

Run tests with pytest:

```bash
cd services/backend
pip install -r requirements.txt
pytest test_family_os.py -v
```

Test coverage includes:
- Decision creation (binary, ranked choice, with deadlines)
- Voting (cast, update, with rationale)
- Conflict detection (disagreement, stalemate)
- Resolution suggestions (rule-based, AI-driven)
- Decision archival with lessons learned
- Full workflow integration tests

## Integration Points

### With Orchestrator

- Decisions can be triggered from conversations ("We need to decide about...")
- Resolution outcomes feed into memory/knowledge system
- Conflict patterns inform relationship stress inference

### With Home Assistant

- Decision outcomes can trigger automations (kitchen reno → update room registry)
- HA sensors can show current open decisions

### With Neo4j Knowledge Graph

- Decision history enriches relationship knowledge
- Resolution patterns inform future suggestions

## Future Enhancements (Phase 4+)

- **Family Memory** — Photo/event timeline, "on this day" memories
- **Multi-Person Households** — Extend beyond couples to families
- **Voting Transparency** — Public rationale sharing
- **Prediction** — ML model predicts likely outcomes
- **Integration** with calendar (auto-schedule after decision)
- **Notifications** — Deadline reminders, conflict alerts
- **Analytics Dashboard** — Decision-making patterns over time

## Configuration

Environment variables:

```bash
DATABASE_URL=postgresql://...
LLM_ENDPOINT=http://...
LLM_MODEL=claude-3-sonnet
CONFLICT_DETECTION_ENABLED=true
AI_RESOLUTIONS_ENABLED=false  # Until LLM integrated
```

## Acceptance Criteria (Task #287)

- [x] Couple voting system (binary + ranked choice)
- [x] Decision history log with outcomes
- [x] Conflict resolution suggestions (rule-based)
- [x] Database schema (PostgreSQL)
- [x] REST API endpoints
- [x] Test suite (pytest)
- [x] Documentation

## Related Tasks

- Task #035 — Family OS Phase 1 (Nicole's dashboard + profiles)
- Task #060 — Family OS Phase 2 (stress inference + household pulse)
- Task #090 — Family OS Phase 4 (decision archival)
