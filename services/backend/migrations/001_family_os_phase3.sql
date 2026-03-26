-- Family OS Phase 3: Shared decisions
-- Couple voting, decision history, conflict resolution
-- Target DB: postgresql://homelab:homelab@192.168.0.80:5432/homelab

BEGIN;

-- =========================================================================
-- family_os.users — User profiles for the household
-- =========================================================================
CREATE SCHEMA IF NOT EXISTS family_os;

CREATE TABLE IF NOT EXISTS family_os.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID            NOT NULL,           -- Couples share a household
    name            TEXT            NOT NULL,           -- "Henning", "Nicole"
    email           TEXT,                               -- Optional email
    role            TEXT            NOT NULL DEFAULT 'member', -- 'admin', 'member'
    preferences     JSONB           NOT NULL DEFAULT '{}', -- voting_style, notification_prefs, etc.
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_os_users_household_id
    ON family_os.users (household_id);

-- =========================================================================
-- family_os.decisions — Shared decisions requiring couple voting
-- =========================================================================
CREATE TABLE IF NOT EXISTS family_os.decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID            NOT NULL,           -- Which couple/household
    title           TEXT            NOT NULL,           -- "Should we renovate the kitchen?"
    description     TEXT,                               -- Full context
    category        TEXT            NOT NULL DEFAULT 'general', -- 'finance', 'home', 'travel', 'lifestyle', 'general'
    status          TEXT            NOT NULL DEFAULT 'open', -- 'open', 'resolved', 'archived'
    voting_method   TEXT            NOT NULL DEFAULT 'binary', -- 'binary', 'ranked_choice', 'weighted'
    options         JSONB           NOT NULL,           -- For ranked choice: ["Option A", "Option B", "Option C"]
    created_by      UUID            NOT NULL REFERENCES family_os.users(id),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deadline        TIMESTAMPTZ,                        -- Optional: when votes must be cast
    resolved_at     TIMESTAMPTZ,                        -- When decision was closed
    final_outcome   TEXT,                               -- Which option won or final decision text
    resolution_notes TEXT,                              -- Explanation of how decision was made
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_os_decisions_household_id
    ON family_os.decisions (household_id);

CREATE INDEX IF NOT EXISTS idx_family_os_decisions_status
    ON family_os.decisions (status);

CREATE INDEX IF NOT EXISTS idx_family_os_decisions_created_at
    ON family_os.decisions (created_at DESC);

-- =========================================================================
-- family_os.votes — Individual votes from household members
-- =========================================================================
CREATE TABLE IF NOT EXISTS family_os.votes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id     UUID            NOT NULL REFERENCES family_os.decisions(id) ON DELETE CASCADE,
    voter_id        UUID            NOT NULL REFERENCES family_os.users(id),
    vote_value      TEXT,                               -- "yes"/"no" for binary, ranked array for ranked choice
    rationale       TEXT,                               -- Why they voted this way
    confidence      NUMERIC(3,2),                       -- 0.0-1.0: how sure they are
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE(decision_id, voter_id)                       -- One vote per person per decision
);

CREATE INDEX IF NOT EXISTS idx_family_os_votes_decision_id
    ON family_os.votes (decision_id);

CREATE INDEX IF NOT EXISTS idx_family_os_votes_voter_id
    ON family_os.votes (voter_id);

-- =========================================================================
-- family_os.decision_history — Archive of resolved decisions
-- =========================================================================
CREATE TABLE IF NOT EXISTS family_os.decision_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID            NOT NULL,           -- Track history per couple
    decision_id     UUID            NOT NULL REFERENCES family_os.decisions(id),
    original_title  TEXT            NOT NULL,           -- Title at time of resolution
    voting_summary  JSONB           NOT NULL,           -- {"user_name": "vote_value", ...}
    final_outcome   TEXT            NOT NULL,           -- What was decided
    resolution_method TEXT          NOT NULL,           -- 'consensus', 'majority', 'weighted_vote', 'discussion', 'compromise'
    impact_assessment TEXT,                             -- Was it the right call? Looking back
    learned_lessons JSONB           NOT NULL DEFAULT '[]', -- ["lesson 1", "lesson 2"]
    resolved_at     TIMESTAMPTZ     NOT NULL,           -- When it was decided
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_os_decision_history_household_id
    ON family_os.decision_history (household_id);

CREATE INDEX IF NOT EXISTS idx_family_os_decision_history_resolved_at
    ON family_os.decision_history (resolved_at DESC);

-- =========================================================================
-- family_os.conflict_resolutions — AI-generated or manual conflict suggestions
-- =========================================================================
CREATE TABLE IF NOT EXISTS family_os.conflict_resolutions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id     UUID            NOT NULL REFERENCES family_os.decisions(id) ON DELETE CASCADE,
    conflict_type   TEXT            NOT NULL,           -- 'disagreement', 'stalemate', 'competing_values', 'resource_constraint'
    severity        NUMERIC(2,1),                       -- 1.0-10.0: how serious is the conflict
    user1_position  TEXT,                               -- User A's stance
    user2_position  TEXT,                               -- User B's stance
    suggested_resolution JSONB      NOT NULL,           -- {"type": "compromise", "details": "..."}
    source          TEXT            NOT NULL DEFAULT 'rule_based', -- 'ai_generated', 'rule_based', 'manual'
    accepted        BOOLEAN         DEFAULT FALSE,      -- Did they follow the suggestion?
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_os_conflict_resolutions_decision_id
    ON family_os.conflict_resolutions (decision_id);

CREATE INDEX IF NOT EXISTS idx_family_os_conflict_resolutions_conflict_type
    ON family_os.conflict_resolutions (conflict_type);

COMMIT;
