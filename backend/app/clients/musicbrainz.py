"""MusicBrainz client — authoritative metadata/relationships (FR-6, no auth required).

Only a descriptive User-Agent is required by MusicBrainz's API usage policy,
not a credential. `musicbrainzngs` is synchronous, so calls run in a thread
to avoid blocking the event loop.
"""

import asyncio

import musicbrainzngs

from app.config import settings

_APP_NAME = "orchestra-recommender"
_APP_VERSION = "0.1"
_configured = False


def _ensure_configured() -> None:
    global _configured
    if not _configured:
        musicbrainzngs.set_useragent(_APP_NAME, _APP_VERSION, settings.musicbrainz_contact)
        _configured = True


def _search_recordings_sync(query: str, limit: int) -> list[dict]:
    _ensure_configured()
    result = musicbrainzngs.search_recordings(query=query, limit=limit)
    candidates = []
    for recording in result.get("recording-list", []):
        artist_names = [
            credit["artist"]["name"]
            for credit in recording.get("artist-credit", [])
            if isinstance(credit, dict) and "artist" in credit
        ]
        releases = recording.get("release-list", [])
        first_release_date = next((r.get("date") for r in releases if r.get("date")), None)
        candidates.append(
            {
                "source": "musicbrainz",
                "musicbrainz_id": recording.get("id"),
                "title": recording.get("title"),
                "artist": ", ".join(artist_names) if artist_names else None,
                "score": recording.get("ext:score"),
                "first_release_date": first_release_date,
            }
        )
    return candidates


async def search_musicbrainz(query: str, limit: int = 15) -> list[dict]:
    """Resolve authoritative metadata for candidates matching `query`.

    musicbrainzngs uses raw urllib with no timeout and retries up to 8 times
    with a growing sleep on transient errors — live-discovered: a single
    stalled/rate-limited call can otherwise block for minutes. Bounded here
    with wait_for since asyncio.to_thread can't cancel a running thread —
    this only bounds our own wait, not the underlying thread.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(_search_recordings_sync, query, limit),
        timeout=settings.provider_call_timeout_seconds,
    )
