"""HEMS Postgres schema helper (#1040).

Applies all pending SQL migration files in the migrations/ directory.
Idempotent — every migration uses IF NOT EXISTS guards.

Run directly to apply schema:
    python db_schema.py

Or call apply_hems_schema() at startup (after database.py pool init).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Migrations directory is a sibling of this file
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Ordered list of migrations to apply — extend this list when adding new files.
MIGRATIONS: list[str] = [
    "001_hems_schema.sql",
    "002_adaptive_schedules.sql",
    "003_thermal_params_nn_models_decisions.sql",
    "004_pv_allocation.sql",
    "005_hems_public_tables.sql",
    "006_boiler_state_mixer_training.sql",
]


async def apply_hems_schema(
    db_url: str | None = None,
    migrations: list[str] | None = None,
) -> bool:
    """Apply HEMS migrations to Postgres.

    Args:
        db_url: asyncpg-compatible connection URL.  Falls back to
                DATABASE_URL env var, then the homelab default.
        migrations: Override the list of migration filenames to apply.
                    Defaults to the module-level MIGRATIONS list.

    Returns:
        True on success, False on failure.
    """
    import asyncpg

    if db_url is None:
        raw = os.getenv(
            "DATABASE_URL",
            "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
        )
        # Strip SQLAlchemy driver prefixes that asyncpg doesn't understand
        db_url = raw.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg2://", "postgresql://"
        )

    files = migrations if migrations is not None else MIGRATIONS

    try:
        conn = await asyncpg.connect(db_url)
        try:
            for filename in files:
                sql_path = MIGRATIONS_DIR / filename
                if not sql_path.exists():
                    logger.warning("Migration file not found, skipping: %s", sql_path)
                    continue

                sql = sql_path.read_text(encoding="utf-8")
                await conn.execute(sql)
                logger.info("Applied migration: %s", filename)

        finally:
            await conn.close()

        logger.info("HEMS schema applied successfully (%d migrations)", len(files))
        return True

    except Exception as e:
        logger.error("Schema apply failed: %s", e)
        return False


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ok = asyncio.run(apply_hems_schema())
    sys.exit(0 if ok else 1)
