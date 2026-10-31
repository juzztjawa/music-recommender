"""Last.fm client — tag/genre data and similar-artist signal (FR-6).

Plain REST (no official async SDK), so this uses httpx directly rather than
a synchronous library wrapped in a thread.
"""

import asyncio

import httpx

from app.config import settings

_BASE_URL = "http://ws.audioscrobbler.com/2.0/"


class LastfmNotConfigured(RuntimeError):
    pass


async def search_lastfm(artist: str, track: str | None = None) -> dict:
    """Fetch top tags and similar artists for `artist` (and `track`, if given)."""
    if not settings.lastfm_api_key:
        raise LastfmNotConfigured("LASTFM_API_KEY is not set")

    async with httpx.AsyncClient(timeout=10.0) as client:
        tags_params = {
            "method": "track.gettoptags" if track else "artist.gettoptags",
            "artist": artist,
            "api_key": settings.lastfm_api_key,
            "format": "json",
        }
        if track:
            tags_params["track"] = track

        similar_params = {
            "method": "artist.getsimilar",
            "artist": artist,
            "api_key": settings.lastfm_api_key,
            "format": "json",
            "limit": "10",
        }

        tags_resp, similar_resp = await asyncio.gather(
            client.get(_BASE_URL, params=tags_params),
            client.get(_BASE_URL, params=similar_params),
        )

    tags_data = tags_resp.json()
    similar_data = similar_resp.json()

    tags = [t["name"] for t in tags_data.get("toptags", {}).get("tag", [])]
    similar_artists = [a["name"] for a in similar_data.get("similarartists", {}).get("artist", [])]

    return {
        "source": "lastfm",
        "artist": artist,
        "track": track,
        "tags": tags,
        "similar_artists": similar_artists,
    }
