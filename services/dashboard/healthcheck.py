"""Docker healthcheck — verifies the NiceGUI web server is responding."""

import sys

import httpx

try:
    resp = httpx.get("http://localhost:8085/_health", timeout=5.0)
    sys.exit(0 if resp.status_code == 200 else 1)
except Exception:
    sys.exit(1)
