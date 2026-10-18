"""Unit tests for app.services.rate_limit (Phase 7)."""

import time

import pytest

from app.services.rate_limit import RateLimitExceeded, enforce_rate_limit


class FakeRedis:
    """In-memory stand-in for the subset of redis.asyncio.Redis used here."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._expires_at: dict[str, float] = {}

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self._expires_at[key] = time.monotonic() + seconds

    async def ttl(self, key: str) -> int:
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return -1
        return max(int(expires_at - time.monotonic()), 0)


async def test_enforce_rate_limit_allows_requests_within_limit():
    redis = FakeRedis()
    for _ in range(3):
        await enforce_rate_limit(redis, "k", limit=3, window_seconds=60)


async def test_enforce_rate_limit_raises_once_limit_exceeded():
    redis = FakeRedis()
    for _ in range(3):
        await enforce_rate_limit(redis, "k", limit=3, window_seconds=60)

    with pytest.raises(RateLimitExceeded):
        await enforce_rate_limit(redis, "k", limit=3, window_seconds=60)


async def test_enforce_rate_limit_reports_retry_after_from_ttl():
    redis = FakeRedis()
    await enforce_rate_limit(redis, "k", limit=1, window_seconds=60)

    with pytest.raises(RateLimitExceeded) as exc_info:
        await enforce_rate_limit(redis, "k", limit=1, window_seconds=60)

    assert 0 < exc_info.value.retry_after_seconds <= 60


async def test_enforce_rate_limit_keys_are_independent():
    redis = FakeRedis()
    for _ in range(3):
        await enforce_rate_limit(redis, "a", limit=3, window_seconds=60)

    # A different key has its own budget, unaffected by "a" being maxed out.
    await enforce_rate_limit(redis, "b", limit=3, window_seconds=60)
