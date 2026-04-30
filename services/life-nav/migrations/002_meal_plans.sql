-- Life Navigation System — Phase 3 schema additions
-- Cook Planner: meal plan tracking with macro targets

CREATE TABLE IF NOT EXISTS ln_meal_plans (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             VARCHAR(64) NOT NULL,
    plan_date           DATE        NOT NULL,
    breakfast           TEXT        NOT NULL DEFAULT '',
    lunch               TEXT        NOT NULL DEFAULT '',
    dinner              TEXT        NOT NULL DEFAULT '',
    snacks              TEXT        NOT NULL DEFAULT '',
    notes               TEXT        NOT NULL DEFAULT '',
    calories_target     INT,
    protein_g_target    NUMERIC,
    carbs_g_target      NUMERIC,
    fat_g_target        NUMERIC,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ln_meal_plans_user_date ON ln_meal_plans (user_id, plan_date);
CREATE INDEX IF NOT EXISTS ln_meal_plans_created ON ln_meal_plans (created_at DESC);
