"""Spotify playlist client — search public playlists and read their tracks (FR-6).

Why a separate module from `spotify.py`: spotipy still calls the removed
`/playlists/{id}/tracks` endpoint (replaced by `/items` in Spotify's Feb 2026
change) and is synchronous, so this talks to the Web API directly with httpx,
using a Client Credentials token.

Spotify publishes no numeric rate limit: it counts calls per app in a rolling
30-second window and answers 429 with `Retry-After`; development-mode apps
also share an undisclosed quota. So this module (1) caps concurrency, (2) honours
`Retry-After` once, then gives up with `SpotifyRateLimited`, and (3) caches
results in-process, because playlists change slowly and every avoided call
counts. Search `limit` is capped at 10 by Spotify for dev-mode apps.

Verified live on 2026-11-01: with this app's credentials, `/items` returned the
tracks of playlists owned by other users. Spotify's changelog says non-owned
playlists return metadata only, so treat that as "works today" — callers must
tolerate a 403/empty result per playlist.
"""

import asyncio
import time
from typing import Any

import httpx
from spotipy.oauth2 import SpotifyClientCredentials

from app.config import settings

_API = "https://api.spotify.com/v1"
_SEARCH_MAX_LIMIT = 10
_ITEMS_PAGE = 100
_MAX_RETRY_AFTER_SECONDS = 10.0

SEARCH_TTL_SECONDS = 3600
ITEMS_TTL_SECONDS = 6 * 3600

_auth: SpotifyClientCredentials | None = None
_semaphore: asyncio.Semaphore | None = None
_cache: dict[tuple, tuple[float, Any]] = {}


class SpotifyNotConfigured(RuntimeError):
    pass


class SpotifyRateLimited(RuntimeError):
    pass


def _get_auth() -> SpotifyClientCredentials:
    global _auth
    if _auth is None:
        if not (settings.spotify_client_id and settings.spotify_client_secret):
            raise SpotifyNotConfigured("SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are not set")
        _auth = SpotifyClientCredentials(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )
    return _auth


def _gate() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.spotify_playlist_concurrency)
    return _semaphore


def _cache_get(key: tuple) -> Any | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    _cache.pop(key, None)
    return None


def _cache_put(key: tuple, value: Any, ttl: float) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


async def _get(path: str, params: dict[str, Any]) -> dict | None:
    """GET with a bearer token, one Retry-After retry. None on 403/404 (skip that playlist)."""
    token = await asyncio.to_thread(_get_auth().get_access_token, False)
    headers = {"Authorization": f"Bearer {token}"}
    async with _gate(), httpx.AsyncClient(timeout=15.0) as client:
        for attempt in (1, 2):
            resp = await client.get(f"{_API}{path}", params=params, headers=headers)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", "1"))
                if attempt == 2 or wait > _MAX_RETRY_AFTER_SECONDS:
                    raise SpotifyRateLimited(f"Spotify 429 on {path}; Retry-After={wait}s")
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (403, 404):
                return None
            resp.raise_for_status()
            return resp.json()
    return None  # unreachable; keeps type checkers happy


async def search_playlists(query: str, limit: int = 10, offset: int = 0) -> list[dict]:
    """Public playlists whose name/description match `query` (most relevant first)."""
    limit = max(1, min(limit, _SEARCH_MAX_LIMIT))
    key = ("search", query.strip().lower(), limit, offset)
    if (cached := _cache_get(key)) is not None:
        return cached
    data = await _get("/search", {"q": query, "type": "playlist", "limit": limit, "offset": offset})
    items = ((data or {}).get("playlists") or {}).get("items") or []
    playlists = [
        {
            "id": p["id"],
            "name": p.get("name") or "",
            "description": p.get("description") or "",
            "owner_id": (p.get("owner") or {}).get("id") or "",
            "owner_name": (p.get("owner") or {}).get("display_name") or "",
            "total": ((p.get("items") or p.get("tracks")) or {}).get("total"),
            "url": (p.get("external_urls") or {}).get("spotify"),
        }
        for p in items
        if p and p.get("id")  # Spotify search returns null entries
    ]
    _cache_put(key, playlists, SEARCH_TTL_SECONDS)
    return playlists


async def get_playlist_tracks(playlist_id: str, max_tracks: int = 200) -> list[dict] | None:
    """Ordered tracks of a playlist (position preserved), or None if not readable.

    Local files, podcast episodes and unavailable items are skipped but still
    occupy a position, so neighbour distances stay true to the author's order.
    """
    key = ("items", playlist_id, max_tracks)
    if (cached := _cache_get(key)) is not None:
        return cached or None  # [] is cached as "unreadable"
    tracks: list[dict] = []
    position = 0
    offset = 0
    readable = True
    while offset < max_tracks:
        data = await _get(
            f"/playlists/{playlist_id}/items",
            {"limit": min(_ITEMS_PAGE, max_tracks - offset), "offset": offset},
        )
        if data is None:
            readable = offset > 0
            break
        page = data.get("items") or []
        for entry in page:
            item = (entry or {}).get("item") or (entry or {}).get("track") or {}
            if item.get("id") and item.get("type", "track") == "track" and not item.get("is_local"):
                tracks.append(
                    {
                        "position": position,
                        "spotify_id": item["id"],
                        "title": item.get("name") or "",
                        "artists": [a["name"] for a in item.get("artists", []) if a.get("name")],
                        "url": (item.get("external_urls") or {}).get("spotify"),
                    }
                )
            position += 1
        offset += len(page)
        if len(page) < _ITEMS_PAGE or not data.get("next"):
            break
    _cache_put(key, tracks if readable else [], ITEMS_TTL_SECONDS)
    return tracks if readable else None
