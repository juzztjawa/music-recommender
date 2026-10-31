"""Tests for Spotify token storage/refresh (app.services.spotify_oauth)."""

import time
from types import SimpleNamespace

import httpx
import pytest

from app.services import spotify_oauth
from app.services.spotify_oauth import SpotifyAuthError


class FakeDb:
    """Stands in for AsyncSession: save_tokens only calls add() and commit()."""

    def add(self, _obj): ...

    async def commit(self): ...


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(spotify_oauth.settings, "spotify_client_id", "cid")
    monkeypatch.setattr(spotify_oauth.settings, "spotify_client_secret", "sec")


def identity_with(tokens):
    return SimpleNamespace(
        spotify_oauth_token=spotify_oauth.encrypt_tokens(tokens) if tokens else None
    )


def test_encryption_round_trip_and_tamper():
    blob = spotify_oauth.encrypt_tokens({"access_token": "a"})
    assert "access_token" not in blob  # not stored in the clear
    assert spotify_oauth.decrypt_tokens(blob) == {"access_token": "a"}
    assert spotify_oauth.decrypt_tokens(blob[:-4] + "AAAA") is None
    assert spotify_oauth.decrypt_tokens("garbage") is None


async def test_valid_token_is_returned_without_network():
    ident = identity_with(
        {"access_token": "live", "refresh_token": "r", "expires_at": time.time() + 3600}
    )
    assert await spotify_oauth.get_access_token(FakeDb(), ident) == "live"


async def test_expired_token_is_refreshed_and_keeps_old_refresh_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    ident = identity_with({"access_token": "old", "refresh_token": "r1", "expires_at": 0})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await spotify_oauth.get_access_token(FakeDb(), ident, client)

    assert token == "new"
    assert "grant_type=refresh_token" in seen["body"]
    stored = spotify_oauth.decrypt_tokens(ident.spotify_oauth_token)
    assert stored["access_token"] == "new" and stored["refresh_token"] == "r1"


async def test_revoked_grant_clears_tokens():
    def handler(_request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    ident = identity_with({"access_token": "old", "refresh_token": "r1", "expires_at": 0})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SpotifyAuthError):
            await spotify_oauth.get_access_token(FakeDb(), ident, client)
    assert ident.spotify_oauth_token is None
    assert not spotify_oauth.is_connected(ident)


async def test_not_connected_raises():
    with pytest.raises(SpotifyAuthError):
        await spotify_oauth.get_access_token(FakeDb(), identity_with(None))


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def getdel(self, key):
        return self.data.pop(key, None)


async def test_state_is_single_use_and_url_has_required_params():
    import uuid
    from urllib.parse import parse_qs, urlparse

    redis, ident_id, run_id = FakeRedis(), uuid.uuid4(), uuid.uuid4()
    url = await spotify_oauth.create_authorize_url(redis, ident_id, run_id)
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"] and q["response_type"] == ["code"]
    assert q["redirect_uri"][0].startswith("http://127.0.0.1")
    assert "playlist-modify-private" in q["scope"][0]

    ctx = await spotify_oauth.consume_state(redis, q["state"][0])
    assert ctx == {"identity_id": str(ident_id), "run_id": str(run_id)}
    assert await spotify_oauth.consume_state(redis, q["state"][0]) is None
    assert await spotify_oauth.consume_state(redis, "forged") is None
