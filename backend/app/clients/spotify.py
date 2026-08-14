"""Spotify client — catalog search via the Client Credentials flow (FR-6).

App-only auth (no user login) is enough for catalog search. The
Authorization Code flow for playlist export (FR-16) is separate and lands in
Phase 8. `spotipy` is synchronous, so calls run in a thread.
"""

import asyncio

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from app.config import settings

_client: spotipy.Spotify | None = None


class SpotifyNotConfigured(RuntimeError):
    pass


def _get_client() -> spotipy.Spotify:
    global _client
    if _client is None:
        if not (settings.spotify_client_id and settings.spotify_client_secret):
            raise SpotifyNotConfigured("SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are not set")
        auth_manager = SpotifyClientCredentials(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )
        _client = spotipy.Spotify(auth_manager=auth_manager)
    return _client


def _search_sync(query: str, limit: int) -> list[dict]:
    client = _get_client()
    result = client.search(q=query, type="track", limit=limit)
    items = result.get("tracks", {}).get("items", [])
    return [
        {
            "source": "spotify",
            "spotify_id": item.get("id"),
            "title": item.get("name"),
            "artist": ", ".join(a["name"] for a in item.get("artists", [])),
            "album": item.get("album", {}).get("name"),
            "release_date": item.get("album", {}).get("release_date"),
            "popularity": item.get("popularity"),
            "url": item.get("external_urls", {}).get("spotify"),
        }
        for item in items
    ]


async def search_spotify(query: str, limit: int = 20) -> list[dict]:
    """Search Spotify's catalog for candidate tracks matching `query`."""
    return await asyncio.to_thread(_search_sync, query, limit)
