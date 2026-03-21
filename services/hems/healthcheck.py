"""Docker healthcheck script for HEMS service."""

import sys
from pathlib import Path

HEALTHCHECK_FILE = Path("/app/data/healthcheck")

if HEALTHCHECK_FILE.exists():
    sys.exit(0)
else:
    sys.exit(1)
