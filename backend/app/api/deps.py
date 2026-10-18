"""Shared FastAPI dependencies (DI)."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.identity import Identity
from app.redis import get_redis
from app.services.auth import decode_access_token
from app.services.rate_limit import enforce_rate_limit

__all__ = [
    "enforce_discovery_rate_limit",
    "enforce_request_link_rate_limit",
    "get_current_identity",
    "get_db",
    "get_redis",
]

_bearer_scheme = HTTPBearer()


async def get_current_identity(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    identity_id = decode_access_token(credentials.credentials)
    if identity_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(Identity).where(Identity.id == identity_id))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=401, detail="Identity not found")

    return identity


async def enforce_discovery_rate_limit(
    identity: Identity = Depends(get_current_identity),
    redis: Redis = Depends(get_redis),
) -> None:
    """Shared across /discover, /retrieve, /analyze-audio — they all draw on
    the same YouTube quota and Ollama Cloud balance, so the budget is shared
    too, not tracked per route."""
    await enforce_rate_limit(
        redis,
        f"ratelimit:identity:{identity.id}:discovery",
        limit=settings.rate_limit_discovery_per_identity_per_hour,
        window_seconds=3600,
    )
    await enforce_rate_limit(
        redis,
        "ratelimit:global:discovery",
        limit=settings.rate_limit_discovery_global_per_day,
        window_seconds=86400,
    )


async def enforce_request_link_rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    """IP-scoped, not identity-scoped — this runs before login exists, and
    caps magic-link spam / email-enumeration probing."""
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        redis,
        f"ratelimit:ip:{client_ip}:request-link",
        limit=settings.rate_limit_request_link_per_ip_per_hour,
        window_seconds=3600,
    )
