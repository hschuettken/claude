"""Bifrost-style JWT auth for Agent Economy API.

Agents obtain a token via POST /api/v1/auth/token and include it as
  Authorization: Bearer <token>
in subsequent requests. The JWT encodes the agent_id and agent_name.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

logger = logging.getLogger(__name__)

try:
    import jwt as _jwt  # PyJWT
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False

_bearer = HTTPBearer(auto_error=False)


def create_token(agent_id: str, agent_name: str) -> str:
    if not _JWT_AVAILABLE:
        # Fallback: plain base64 pseudo-token (dev only)
        import base64, json
        payload = {"sub": agent_id, "name": agent_name}
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": agent_id,
        "name": agent_name,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    if not _JWT_AVAILABLE:
        import base64, json
        try:
            return json.loads(base64.urlsafe_b64decode(token + "=="))
        except Exception:
            return None
    try:
        return _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return None


async def get_current_agent(
    authorization: Optional[str] = Header(default=None),
) -> Optional[dict]:
    """Extract agent info from JWT. Returns None when token absent (public endpoints)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def require_agent(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Like get_current_agent but raises 401 when no valid token."""
    payload = await get_current_agent(authorization)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
