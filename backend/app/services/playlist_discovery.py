"""Find candidate songs from user-built Spotify playlists (docs/09-playlist-evidence.md).

search playlists → rank/fetch a bounded number → score (see playlist_scoring) .
All Spotify calls go through `app.clients.spotify_playlists`, which owns rate
limiting and caching. Failures on one playlist or one search never fail the call.
"""

import asyncio
import logging
from dataclasses import asdict

from app.clients import spotify_playlists as sp
from app.config import settings
from app.services.playlist_scoring import (
    SPOTIFY_OWNER_ID,
    PlaylistInput,
    ScoredCandidate,
    Seed,
    score_candidates,
)

logger = logging.getLogger(__name__)


def _search_queries(seeds: list[Seed], vibe_queries: list[str]) -> list[str]:
    """Vibe text first (it describes the playlist theme), then artist-flavoured ones.

    Spotify playlist search matches playlist name/description only — it cannot
    find "playlists containing song X" — so seeds help only through their names.
    """
    queries = [q.strip() for q in vibe_queries if q.strip()]
    for seed in seeds:
        queries.append(f"{seed.artist} {seed.title}")
        queries.append(f"songs like {seed.artist}")
    seen: set[str] = set()
    ordered = [q for q in queries if not (q.lower() in seen or seen.add(q.lower()))]
    return ordered[: settings.playlist_max_searches]


def _rank_for_fetch(found: list[dict], seeds: list[Seed]) -> list[dict]:
    """Which playlists deserve one of the limited fetches: prefer user-built,
    plausible size, and names mentioning a seed artist."""
    artist_words = {w for s in seeds for w in s.artist.lower().split()}

    def priority(p: dict) -> tuple:
        user_built = p["owner_id"] != SPOTIFY_OWNER_ID
        total = p.get("total")
        sized = total is None or 8 <= total <= 400
        mentions = bool(artist_words & set(f"{p['name']} {p['description']}".lower().split()))
        return (user_built, sized, mentions)

    return sorted(found, key=priority, reverse=True)


async def discover_from_playlists(
    seeds: list[Seed], vibe_queries: list[str], limit: int = 40
) -> dict:
    """Return scored candidates plus a `stats` dict describing how much evidence backed them."""
    queries = _search_queries(seeds, vibe_queries)
    results = await asyncio.gather(
        *(sp.search_playlists(q) for q in queries), return_exceptions=True
    )
    found: dict[str, dict] = {}
    errors: list[str] = []
    for query, res in zip(queries, results, strict=True):
        if isinstance(res, Exception):
            logger.warning("playlist search failed for %r: %s", query, res)
            errors.append(f"search {query!r}: {res}")
            continue
        for p in res:
            found.setdefault(p["id"], p)

    chosen = _rank_for_fetch(list(found.values()), seeds)[: settings.playlist_max_fetches]
    fetched = await asyncio.gather(
        *(sp.get_playlist_tracks(p["id"], settings.playlist_max_tracks) for p in chosen),
        return_exceptions=True,
    )
    inputs: list[PlaylistInput] = []
    unreadable = 0
    for p, res in zip(chosen, fetched, strict=True):
        if isinstance(res, Exception):
            errors.append(f"playlist {p['id']}: {res}")
            unreadable += 1
        elif res is None:
            unreadable += 1
        else:
            inputs.append(PlaylistInput(p["id"], p["name"], p["description"], p["owner_id"], res))

    scored: list[ScoredCandidate] = score_candidates(
        inputs,
        seeds,
        query=" ".join(vibe_queries),
        editorial_weight=settings.playlist_editorial_weight,
        limit=limit,
    )
    return {
        "candidates": [asdict(c) for c in scored],
        "stats": {
            "searches": len(queries),
            "playlists_found": len(found),
            "playlists_read": len(inputs),
            "playlists_unreadable": unreadable,
            "errors": errors[:5],
        },
    }
