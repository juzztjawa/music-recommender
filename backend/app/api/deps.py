"""Shared FastAPI dependencies (DI)."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.identity import Identity
from app.redis import get_redis
from app.services.auth import decode_access_token

__all__ = ["get_current_identity", "get_db", "get_redis"]

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
