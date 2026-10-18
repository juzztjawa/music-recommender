"""YouTube Music client — candidate search via ytmusicapi (FR-6).

Unauthenticated search works out of the box, no credentials needed. This is
the least stable of the six providers (unofficial API — architecture.md §9),
which is why it's built last. `ytmusicapi` is synchronous, so calls run in a
thread.
"""

import asyncio

from ytmusicapi import YTMusic

from app.config import settings

_client: YTMusic | None = None


def _get_client() -> YTMusic:
    global _client
    if _client is None:
        _client = YTMusic()
    return _client


def _search_sync(query: str, limit: int) -> list[dict]:
    client = _get_client()
    results = client.search(query, filter="songs", limit=limit)
    return [
        {
            "source": "youtube_music",
            "video_id": item.get("videoId"),
            "title": item.get("title"),
            "artist": ", ".join(a["name"] for a in item.get("artists", []) or []),
            "album": (item.get("album") or {}).get("name"),
            "duration_seconds": item.get("duration_seconds"),
            "views": item.get("views"),
        }
        for item in results
    ]


async def search_youtube_music(query: str, limit: int = 15) -> list[dict]:
    """Search YouTube Music for candidate tracks matching `query`.

    ytmusicapi has no built-in request timeout, so this bounds our own wait
    the same way app/clients/musicbrainz.py does.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(_search_sync, query, limit),
        timeout=settings.provider_call_timeout_seconds,
    )
