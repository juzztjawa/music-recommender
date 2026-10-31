"""ENVIRONMENT=test exposes the magic link in the response; every other
environment must not (it would let anyone sign in as any email)."""

import httpx
import pytest

from app.api.deps import get_redis
from app.api.routes import auth as auth_routes
from app.app import app
from app.config import settings


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, *_a): ...

    async def ttl(self, _key):
        return 60

    async def set(self, key, value, ex=None):
        self.data[key] = value


@pytest.fixture
async def client(monkeypatch):
    async def no_email(*_a): ...

    monkeypatch.setattr(auth_routes, "send_magic_link_email", no_email)
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("env", "exposed"), [("test", True), ("development", False), ("production", False)]
)
async def test_dev_link_only_in_test(client, monkeypatch, env, exposed):
    monkeypatch.setattr(settings, "environment", env)
    resp = await client.post("/api/auth/request-link", json={"email": "a@example.com"})
    assert resp.status_code == 200
    assert ("dev_link" in resp.json()) is exposed
    if exposed:
        assert resp.json()["dev_link"].startswith(f"{settings.frontend_base_url}/verify?token=")
