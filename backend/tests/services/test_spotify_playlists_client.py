"""spotify_playlists: Retry-After handling, null search entries, 403 → unreadable, caching."""

import httpx
import pytest

from app.clients import spotify_playlists as sp


class FakeAuth:
    def get_access_token(self, as_dict=False):
        return "tok"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sp._cache.clear()
    sp._semaphore = None
    monkeypatch.setattr(sp, "_auth", FakeAuth())


def install(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        sp.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def test_search_skips_null_entries_and_caches(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req.url)
        return httpx.Response(
            200,
            json={
                "playlists": {
                    "items": [
                        None,
                        {
                            "id": "a",
                            "name": "N",
                            "owner": {"id": "u", "display_name": "U"},
                            "items": {"total": 40},
                        },
                    ]
                }
            },
        )

    install(monkeypatch, handler)
    first = await sp.search_playlists("sad indie")
    again = await sp.search_playlists("Sad Indie ")
    assert [p["id"] for p in first] == ["a"] and first[0]["total"] == 40
    assert again == first and len(calls) == 1


async def test_429_is_retried_once_then_raises(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(sp.asyncio, "sleep", no_sleep)
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"})

    install(monkeypatch, handler)
    with pytest.raises(sp.SpotifyRateLimited):
        await sp.search_playlists("x")
    assert n["c"] == 2


async def test_unreadable_playlist_returns_none_and_items_parse_positions(monkeypatch):
    def handler(req):
        if "locked" in req.url.path:
            return httpx.Response(403)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "item": {
                            "id": "t1",
                            "type": "track",
                            "name": "One",
                            "artists": [{"name": "A"}],
                        }
                    },
                    {"item": {"id": "e1", "type": "episode", "name": "Pod"}},
                    {"item": {"id": "l", "type": "track", "is_local": True, "name": "Local"}},
                    {
                        "item": {
                            "id": "t2",
                            "type": "track",
                            "name": "Two",
                            "artists": [{"name": "B"}],
                        }
                    },
                ],
                "next": None,
            },
        )

    install(monkeypatch, handler)
    assert await sp.get_playlist_tracks("locked") is None
    got = await sp.get_playlist_tracks("ok")
    assert [(t["position"], t["title"]) for t in got] == [(0, "One"), (3, "Two")]
