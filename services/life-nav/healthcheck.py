"""Docker healthcheck — exits 0 if service is healthy, 1 otherwise."""
import pathlib
import sys
import time

HEALTHCHECK_FILE = pathlib.Path("/app/data/healthcheck")
MAX_AGE_SECONDS = 300  # 5 minutes

if not HEALTHCHECK_FILE.exists():
    print("UNHEALTHY: healthcheck file missing")
    sys.exit(1)

age = time.time() - HEALTHCHECK_FILE.stat().st_mtime
if age > MAX_AGE_SECONDS:
    print(f"UNHEALTHY: healthcheck file is {age:.0f}s old (max {MAX_AGE_SECONDS}s)")
    sys.exit(1)

print(f"HEALTHY: healthcheck file updated {age:.0f}s ago")
sys.exit(0)
