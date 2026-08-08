"""Health check endpoint.

Reports app, database, and Redis status so the operator can confirm the
skeleton is wired up correctly.
"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis import get_redis

router = APIRouter()


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    status = {"app": "ok", "database": "ok", "redis": "ok"}

    # Database
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        status["database"] = "unreachable"

    # Redis
    try:
        await redis.ping()
    except Exception:  # noqa: BLE001
        status["redis"] = "unreachable"

    return status
