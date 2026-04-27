"""Docker HEALTHCHECK — verifies the service is alive via /health endpoint."""
import sys
import httpx
from digital_twin.config import settings

try:
    r = httpx.get(f"http://localhost:{settings.port}/health", timeout=5)
    if r.status_code == 200 and r.json().get("status") == "ok":
        sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
