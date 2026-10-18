"""Redis-backed fixed-window rate limiting (Phase 7, architecture.md §7).

Protects two things a public demo can burn through fast: the shared Ollama
Cloud balance (every /discover call fires 3-4 LLM calls) and the YouTube
Data API's ~100 searches/day ceiling (search.list = 100 units of a
10,000/day quota, and the Retrieval Agent can call search several times per
hypothesis). Fixed-window counters via Redis INCR+EXPIRE are enough here —
this isn't defending against a sophisticated attacker, just keeping one
enthusiastic user (or a trickle of new signups) from exhausting a budget
that has to last the whole demo window.
"""

from redis.asyncio import Redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded, retry after {retry_after_seconds}s")


async def enforce_rate_limit(redis: Redis, key: str, *, limit: int, window_seconds: int) -> None:
    """Fixed-window counter: INCR the window's key, set its expiry on first hit.

    A fixed window (not sliding log) can let a burst through right at the
    window boundary — acceptable here since the limits below are daily/hourly
    budget caps, not abuse-prevention against a determined attacker.
    """
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)

    if count > limit:
        ttl = await redis.ttl(key)
        raise RateLimitExceeded(retry_after_seconds=ttl if ttl > 0 else window_seconds)
