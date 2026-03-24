#!/usr/bin/env python3
"""
Migration runner for marketing-agent database.
Applies SQL migrations in order to PostgreSQL.
"""

import os
import sys
import subprocess
from pathlib import Path

# Database configuration
DB_HOST = os.getenv("DB_HOST", "192.168.0.80")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "homelab")
DB_USER = os.getenv("DB_USER", "homelab")
DB_PASSWORD = os.getenv("DB_PASSWORD", "homelab")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migration(migration_file: Path) -> bool:
    """Run a single SQL migration file."""
    print(f"Running migration: {migration_file.name}")
    
    # Set up environment for psql
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    
    try:
        cmd = [
            "psql",
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "-f", str(migration_file),
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"✗ Failed: {migration_file.name}")
            print(f"  Error: {result.stderr}")
            return False
        
        print(f"✓ Applied: {migration_file.name}")
        return True
    
    except Exception as e:
        print(f"✗ Exception running {migration_file.name}: {e}")
        return False


def main():
    """Run all SQL migrations in order."""
    # Only run .sql files, in sorted order
    sql_files = sorted([f for f in MIGRATIONS_DIR.glob("*.sql")])
    
    if not sql_files:
        print("No SQL migration files found.")
        return 0
    
    print(f"Found {len(sql_files)} SQL migration files.")
    print(f"Connecting to PostgreSQL at {DB_HOST}:{DB_PORT}/{DB_NAME}\n")
    
    failed = []
    for migration_file in sql_files:
        if not run_migration(migration_file):
            failed.append(migration_file.name)
    
    print("\n" + "=" * 60)
    if failed:
        print(f"✗ {len(failed)} migration(s) failed:")
        for f in failed:
            print(f"  - {f}")
        return 1
    else:
        print(f"✓ All {len(sql_files)} migrations applied successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
