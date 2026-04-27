"""Docker HEALTHCHECK — verifies the service is alive via /health endpoint."""
import sys
import httpx
from self_optimizing_infra.config import settings

try:
    r = httpx.get(f"http://localhost:{settings.port}/health", timeout=5)
    if r.status_code == 200 and r.json().get("status") in ("ok", "degraded"):
        sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
