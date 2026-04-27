# life-nav — Life Navigation System

Personal life modelling, goal tracking, Monte Carlo financial simulation,
health metrics tracking, career milestone planning, and an opportunities radar.
Implements FR #4 / item #40 across all four phases.

## Architecture

- **Framework**: FastAPI at port 8243
- **Storage**: PostgreSQL (192.168.0.80:5432)
- **Event Bus**: NATS JetStream — publishes life events
- **Monte Carlo**: numpy-based, 1000 simulations by default

## Key modules

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app + all endpoints + NATS + Oracle registration |
| `models.py` | Pydantic request/response models |
| `monte_carlo.py` | Monte Carlo simulation engine (p10/p50/p90 trajectories, FI age) |
| `db.py` | asyncpg pool + graceful no-op when DB unavailable |
| `config.py` | Settings from env vars |

## Database tables

| Table | Purpose |
|-------|---------|
| `ln_life_model` | Financial + life parameters (net worth, income, FI target) |
| `ln_goals` | Goal tracking with progress, milestones, life areas |
| `ln_weekly_reviews` | Weekly structured reflection |
| `ln_health_metrics` | Fitness data (weight, VO2max, training hours) |
| `ln_career_milestones` | Career planning and achievement tracking |
| `ln_simulations` | Monte Carlo run history + p10/p50/p90 trajectories |
| `ln_opportunities` | "Opportunities This Week" card items |

## NATS subjects

| Subject | Direction | Purpose |
|---------|-----------|---------|
| `life.goal.completed` | publish | Goal marked completed |
| `life.simulation.run` | publish | Monte Carlo simulation completed |
| `life.review.created` | publish | Weekly review submitted |

## API endpoints

- `GET|PUT /api/v1/model` — Get/upsert life model
- `GET|POST /api/v1/goals` — List/create goals
- `GET|PATCH|DELETE /api/v1/goals/{id}` — Manage individual goals
- `GET|POST /api/v1/weekly-reviews` — List/create weekly reviews
- `GET /api/v1/weekly-reviews/{id}` — Get single review
- `GET|POST /api/v1/health-metrics` — List/log health metrics
- `GET /api/v1/health-metrics/latest` — Latest health metric
- `GET|POST /api/v1/career` — List/create career milestones
- `GET|PATCH /api/v1/career/{id}` — Get/update milestone
- `POST /api/v1/simulation/run` — Run Monte Carlo (returns p10/p50/p90 + FI age)
- `GET /api/v1/simulation/runs` — List previous simulation runs
- `GET /api/v1/simulation/runs/{id}` — Get simulation run
- `GET /api/v1/simulation/fi-projection` — Quick FI age projection (no DB write)
- `GET|POST /api/v1/opportunities` — List/add opportunities
- `DELETE /api/v1/opportunities/{id}` — Remove opportunity
- `GET /api/v1/dashboard` — Aggregated life dashboard card

## Monte Carlo model

Each simulation:
1. Samples `annual_return ~ N(return_mean, return_std)` per year
2. Samples `annual_inflation ~ N(inflation_mean, inflation_std)` per year
3. Net worth grows: `nw[y+1] = (nw[y] + annual_savings[y]) * (1 + return[y])`
4. Income grows at `income_growth_pct` per year
5. Expenses grow at `inflation[y]` per year

FI crossing = first year where `net_worth >= target_monthly_expense * 12 / withdrawal_rate`

p10/p50/p90 = 10th/50th/90th percentile of paths at each year.

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `LIFE_NAV_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL DSN |
| `NATS_URL` | `nats://192.168.0.50:4222` | NATS server |
| `ORACLE_URL` | `http://192.168.0.50:8225` | Integration Oracle |
| `LIFE_NAV_PORT` | `8243` | Service port |
| `LIFE_NAV_USER` | `henning` | Default user ID (single-user) |
| `LIFE_NAV_MC_SIMULATIONS` | `1000` | Number of Monte Carlo paths |
| `LIFE_NAV_MC_RETURN_MEAN` | `0.07` | Expected annual return |
| `LIFE_NAV_MC_RETURN_STD` | `0.15` | Annual return volatility |
| `LIFE_NAV_MC_INFLATION_MEAN` | `0.03` | Expected annual inflation |
| `LIFE_NAV_MC_INFLATION_STD` | `0.01` | Inflation volatility |

## Testing

```bash
cd services/life-nav
python -m pytest tests/ -v
```

Tests run without a real database or NATS connection.
