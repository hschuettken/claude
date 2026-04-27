-- Life Navigation System — schema init
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- Life Model
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_life_model (
    id                          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                     VARCHAR(64) NOT NULL,
    birth_year                  INT         NOT NULL DEFAULT 1990,
    target_retirement_age       INT         NOT NULL DEFAULT 55,
    current_net_worth           NUMERIC     NOT NULL DEFAULT 0,
    monthly_income              NUMERIC     NOT NULL DEFAULT 0,
    monthly_expenses            NUMERIC     NOT NULL DEFAULT 0,
    monthly_savings_rate        NUMERIC,                           -- override; NULL = auto (income-expenses)
    investment_return_pct       NUMERIC     NOT NULL DEFAULT 0.07, -- annual expected return
    passive_income_monthly      NUMERIC     NOT NULL DEFAULT 0,
    target_fi_monthly_expense   NUMERIC     NOT NULL DEFAULT 3000,
    withdrawal_rate             NUMERIC     NOT NULL DEFAULT 0.04, -- SWR
    income_growth_pct           NUMERIC     NOT NULL DEFAULT 0.03,
    notes                       TEXT,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_life_model_user ON ln_life_model (user_id, updated_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Goals
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_goals (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(64) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    life_area       VARCHAR(64) NOT NULL DEFAULT 'other',
    target_date     DATE,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',  -- active, completed, abandoned, paused
    progress_pct    NUMERIC     NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    milestones      JSONB       NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_goals_user        ON ln_goals (user_id, status);
CREATE INDEX IF NOT EXISTS ln_goals_area        ON ln_goals (user_id, life_area);
CREATE INDEX IF NOT EXISTS ln_goals_created     ON ln_goals (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Weekly Reviews
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_weekly_reviews (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(64) NOT NULL,
    week_start      DATE        NOT NULL,
    accomplishments TEXT        NOT NULL DEFAULT '',
    challenges      TEXT        NOT NULL DEFAULT '',
    learnings       TEXT        NOT NULL DEFAULT '',
    next_week_focus TEXT        NOT NULL DEFAULT '',
    energy_level    INT         NOT NULL DEFAULT 5 CHECK (energy_level BETWEEN 1 AND 10),
    mood            INT         NOT NULL DEFAULT 5 CHECK (mood BETWEEN 1 AND 10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ln_reviews_user_week  ON ln_weekly_reviews (user_id, week_start);
CREATE INDEX IF NOT EXISTS ln_reviews_created           ON ln_weekly_reviews (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Health Metrics
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_health_metrics (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             VARCHAR(64) NOT NULL,
    measured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    weight_kg           NUMERIC,
    resting_hr          INT,
    vo2max_estimated    NUMERIC,
    sleep_hours_avg     NUMERIC,
    training_hours_week NUMERIC,
    source              VARCHAR(64) NOT NULL DEFAULT 'manual',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_health_user       ON ln_health_metrics (user_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS ln_health_measured   ON ln_health_metrics (measured_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Career Milestones
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_career_milestones (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(64) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    target_date     DATE,
    achieved_at     DATE,
    status          VARCHAR(32) NOT NULL DEFAULT 'planned',  -- planned, in_progress, achieved, missed
    impact_score    INT         NOT NULL DEFAULT 5 CHECK (impact_score BETWEEN 1 AND 10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_career_user       ON ln_career_milestones (user_id, status);
CREATE INDEX IF NOT EXISTS ln_career_created    ON ln_career_milestones (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Monte Carlo Simulations
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_simulations (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             VARCHAR(64) NOT NULL,
    scenario_name       VARCHAR(128) NOT NULL DEFAULT 'baseline',
    parameters          JSONB       NOT NULL DEFAULT '{}',
    trajectory          JSONB       NOT NULL DEFAULT '[]',
    fi_age_p10          NUMERIC,
    fi_age_p50          NUMERIC,
    fi_age_p90          NUMERIC,
    fi_net_worth_target NUMERIC     NOT NULL DEFAULT 0,
    current_net_worth   NUMERIC     NOT NULL DEFAULT 0,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_sims_user     ON ln_simulations (user_id, run_at DESC);
CREATE INDEX IF NOT EXISTS ln_sims_run_at   ON ln_simulations (run_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Opportunities
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_opportunities (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         VARCHAR(64) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    category        VARCHAR(64) NOT NULL DEFAULT 'other',
    url             TEXT,
    relevance_score NUMERIC     NOT NULL DEFAULT 0.5 CHECK (relevance_score BETWEEN 0 AND 1),
    source          VARCHAR(64) NOT NULL DEFAULT 'manual',
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ln_opp_user      ON ln_opportunities (user_id, category);
CREATE INDEX IF NOT EXISTS ln_opp_relevance ON ln_opportunities (relevance_score DESC);
CREATE INDEX IF NOT EXISTS ln_opp_created   ON ln_opportunities (created_at DESC);
