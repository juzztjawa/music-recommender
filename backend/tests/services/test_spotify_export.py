"""Tests for Spotify playlist export (app.services.spotify_export) — HTTP is
mocked with httpx.MockTransport, so nothing here touches Spotify."""

import json

import httpx
import pytest

from app.services import spotify_export
from app.services.spotify_oauth import SpotifyAuthError

RESULT = {
    "clusters": [
        {
            "theme": "t",
            "input_songs": ["Song X"],
            "recommendations": [
                {"title": "Found Song", "artist": "Good Artist"},
                {"title": "Missing Song", "artist": "Nobody"},
                {"title": "Wrong Artist Song", "artist": "Real Artist"},
                {"title": "found song", "artist": "good artist"},  # duplicate
            ],
        }
    ]
}


def make_client(calls: list[tuple[str, str, dict | None]], *, search_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/v1/search":
            if search_status != 200:
                return httpx.Response(search_status)
            q = request.url.params["q"]
            items = []
            if "Found Song" in q:
                items = [
                    {
                        "name": "Found Song",
                        "uri": "spotify:track:1",
                        "artists": [{"name": "Good Artist"}],
                    }
                ]
            elif "Wrong Artist Song" in q:
                items = [
                    {
                        "name": "Wrong Artist Song",
                        "uri": "spotify:track:2",
                        "artists": [{"name": "Somebody Else"}],
                    }
                ]
            return httpx.Response(200, json={"tracks": {"items": items}})
        if request.url.path == "/v1/me/playlists":
            return httpx.Response(
                201,
                json={
                    "id": "pl1",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
                },
            )
        if request.url.path == "/v1/playlists/pl1/items":
            return httpx.Response(201, json={"snapshot_id": "s"})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_unique_songs_dedupes_case_insensitively():
    assert spotify_export.unique_songs(RESULT) == [
        ("Found Song", "Good Artist"),
        ("Missing Song", "Nobody"),
        ("Wrong Artist Song", "Real Artist"),
    ]


def test_default_name_uses_input_songs_and_is_capped():
    assert spotify_export.default_playlist_name(RESULT) == "Orchestra: Song X"
    long = {"clusters": [{"input_songs": ["x" * 300]}]}
    assert len(spotify_export.default_playlist_name(long)) == 100


async def test_export_adds_only_matches_and_reports_the_rest():
    calls: list = []
    async with make_client(calls) as client:
        out = await spotify_export.export_to_spotify("tok", RESULT, client=client)

    assert out.added == 1
    assert out.playlist_url.endswith("/pl1")
    # Wrong-artist match is rejected, not guessed.
    assert sorted(out.not_found) == ["Missing Song — Nobody", "Wrong Artist Song — Real Artist"]
    created = next(c for c in calls if c[1] == "/v1/me/playlists")
    assert created[2]["public"] is False
    added = next(c for c in calls if c[1] == "/v1/playlists/pl1/items")
    assert added[2] == {"uris": ["spotify:track:1"]}


async def test_nothing_found_raises_and_creates_no_playlist():
    calls: list = []
    only_missing = {
        "clusters": [{"recommendations": [{"title": "Missing Song", "artist": "Nobody"}]}]
    }
    async with make_client(calls) as client:
        with pytest.raises(ValueError):
            await spotify_export.export_to_spotify("tok", only_missing, client=client)
    assert not any(c[1] == "/v1/me/playlists" for c in calls)


async def test_forbidden_maps_to_auth_error():
    async with make_client([], search_status=403) as client:
        with pytest.raises(SpotifyAuthError):
            await spotify_export.export_to_spotify("tok", RESULT, client=client)


async def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(spotify_export.asyncio, "sleep", lambda _s: _noop())
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"tracks": {"items": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await spotify_export.find_track_uri(client, "tok", "A", "B") is None
    assert state["n"] >= 2


async def _noop():
    return None
