"""API key authentication middleware.

Validates X-API-Key header against the configured ORCHESTRATOR_API_KEY.
Exempt paths: /_health (Docker healthcheck).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid API key."""

    def __init__(self, app, api_key: str) -> None:  # type: ignore[override]
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Exempt paths (healthcheck, OpenAPI docs)
        if request.url.path in ("/_health", "/openapi.json", "/docs", "/redoc"):
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if provided != self._api_key:
            return JSONResponse(
                {"error": "Invalid or missing API key"},
                status_code=401,
            )
        return await call_next(request)
