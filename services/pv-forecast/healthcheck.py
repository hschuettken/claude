"""Docker HEALTHCHECK script.

Checks that the service has written a recent healthcheck timestamp.
Exits 0 (healthy) if the file was updated within the last 5 minutes,
1 (unhealthy) otherwise.
"""
import sys
import time
from pathlib import Path

HEALTHCHECK_FILE = Path("/app/data/healthcheck")
MAX_AGE_SECONDS = 300  # 5 minutes

if not HEALTHCHECK_FILE.exists():
    sys.exit(1)

try:
    ts = float(HEALTHCHECK_FILE.read_text().strip())
    age = time.time() - ts
    sys.exit(0 if age < MAX_AGE_SECONDS else 1)
except (ValueError, OSError):
    sys.exit(1)
