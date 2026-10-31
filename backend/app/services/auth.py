"""Auth service logic: magic-link tokens, identity/session creation, JWTs.

Magic-link tokens live in Redis only (TTL matches `magic_link_expire_minutes`)
— they're single-use, short-lived, and have no reason to be durable. Identities
and sessions are Postgres rows per architecture.md §5.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.identity import Identity
from app.models.session import Session

MAGIC_LINK_KEY_PREFIX = "magic_link:"


def generate_magic_link_token() -> str:
    return secrets.token_urlsafe(32)


async def store_magic_link_token(redis: Redis, token: str, email: str) -> None:
    await redis.set(
        f"{MAGIC_LINK_KEY_PREFIX}{token}",
        email,
        ex=timedelta(minutes=settings.magic_link_expire_minutes),
    )


async def consume_magic_link_token(redis: Redis, token: str) -> str | None:
    """Atomically read and delete the token so it can only be used once."""
    # redis_client is configured with decode_responses=True app-wide, so this
    # is always a str at runtime even though the stub's return type is wider.
    result = await redis.getdel(f"{MAGIC_LINK_KEY_PREFIX}{token}")
    return cast(str | None, result)


async def get_or_create_identity(db: AsyncSession, email: str) -> Identity:
    result = await db.execute(select(Identity).where(Identity.email == email))
    identity = result.scalar_one_or_none()
    if identity is not None:
        return identity

    identity = Identity(email=email)
    db.add(identity)
    await db.commit()
    await db.refresh(identity)
    return identity


async def create_session(db: AsyncSession, identity_id: uuid.UUID) -> Session:
    session = Session(identity_id=identity_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


def create_access_token(identity_id: uuid.UUID, session_id: uuid.UUID | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    claims = {"sub": str(identity_id), "exp": expire}
    if session_id is not None:
        claims["sid"] = str(session_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None

    sub = payload.get("sub")
    if sub is None:
        return None

    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


def decode_session_id(token: str) -> uuid.UUID | None:
    """The login session this token was minted for (None for older tokens)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return uuid.UUID(payload["sid"])
    except (JWTError, KeyError, ValueError):
        return None
