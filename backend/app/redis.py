"""Redis client for session state and rate limiting."""

from redis.asyncio import Redis

from app.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)


async def get_redis() -> Redis:
    """FastAPI dependency that yields the shared Redis client."""
    return redis_client
