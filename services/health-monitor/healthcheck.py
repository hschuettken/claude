"""Docker HEALTHCHECK script for health-monitor.

Checks if the service recently wrote a timestamp to /app/data/healthcheck.
If the file is missing or older than 5 minutes, returns exit code 1 (unhealthy).
"""

import sys
import time
from pathlib import Path

HEALTHCHECK_FILE = Path("/app/data/healthcheck")
MAX_AGE_SECONDS = 300  # 5 minutes


def main() -> None:
    if not HEALTHCHECK_FILE.exists():
        sys.exit(1)

    try:
        last_ts = float(HEALTHCHECK_FILE.read_text().strip())
        age = time.time() - last_ts
        if age > MAX_AGE_SECONDS:
            sys.exit(1)
    except (ValueError, OSError):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
