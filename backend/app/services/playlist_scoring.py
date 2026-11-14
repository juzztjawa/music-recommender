"""Score candidate songs from user-built playlists (pure functions, no I/O).

Idea: a playlist author who put your seed song next to other songs is a human
saying "these belong together". Playlists are noisy though, so a candidate must
earn its score through a chain of filters, each cheap and testable:

1. Anchoring  — a playlist counts only if it contains a seed song (full weight)
                or another song by a seed artist (reduced weight).
2. Locality   — playlists are sequenced by vibe, so a track's contribution decays
                with its distance from the seed's position in that playlist.
3. Owner cap  — one owner contributes at most once per track, so a person with
                20 near-identical playlists cannot manufacture consensus.
4. Weighting  — user-built playlists count fully, Spotify-owned (editorial) ones
                are down-weighted; very large "dump" playlists are discounted.
5. Rarity     — scores are divided by how common a track is across ALL fetched
                playlists (IDF), so globally popular songs don't win every query.
6. Support    — a candidate needs ≥ `min_owners` independent owners, unless too
                few candidates survive, in which case weak ones are kept and flagged.

The numbers below are starting points, not tuned values — see
tests/services/test_playlist_scoring.py for the behaviour they must preserve.
"""

import math
import re
import unicodedata
from dataclasses import dataclass, field

SPOTIFY_OWNER_ID = "spotify"

LOCALITY_HALF_LIFE = 8.0  # positions; weight halves roughly every 8 tracks from the seed
LOCALITY_FLOOR = 0.15  # tracks far from the seed still count a little (same playlist, same author)
ARTIST_ONLY_ANCHOR = 0.35  # playlist has the seed artist but not the seed song
EXTRA_SEED_BONUS = 0.25  # per additional distinct seed matched in the same playlist (capped)
MAX_EXTRA_SEED_BONUS = 0.75
SIZE_SWEET_SPOT = (15, 150)
MIN_PLAYLIST_TRACKS = 8
MAX_PER_ARTIST = 4  # keeps one artist's discography from filling the pool
MAX_PER_SEED_ARTIST = 2  # "more of the same artist" is the obvious answer, not a discovery

_PAREN = re.compile(r"[\(\[].*?[\)\]]")
_SUFFIX = re.compile(
    r"\s+-\s+.*(remaster|version|mix|edit|live|mono|stereo|bonus|demo|acoustic|session).*$"
)
_VARIANT = re.compile(r"\b(live|cover|remix|karaoke|sped up|slowed|reverb|8d|nightcore)\b", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def norm_title(title: str) -> str:
    title = _SUFFIX.sub("", _PAREN.sub("", title.lower()))
    return _fold(title)


def norm_artist(artist: str) -> str:
    return _fold(artist)


def track_key(title: str, artists: list[str]) -> tuple[str, str]:
    return norm_title(title), norm_artist(artists[0]) if artists else ""


@dataclass(frozen=True)
class Seed:
    title: str
    artist: str


@dataclass
class PlaylistInput:
    id: str
    name: str
    description: str
    owner_id: str
    tracks: list[dict]  # {position, spotify_id, title, artists, url}


@dataclass
class ScoredCandidate:
    title: str
    artist: str
    spotify_id: str | None
    url: str | None
    score: float  # 0-1, relative to the best candidate of this call
    playlists: int
    owners: int
    user_owners: int
    best_locality: float
    example_playlists: list[str] = field(default_factory=list)
    variant_hint: str = "original"
    weak: bool = False  # True when kept despite fewer than min_owners owners


def _size_factor(n: int) -> float:
    lo, hi = SIZE_SWEET_SPOT
    if n < MIN_PLAYLIST_TRACKS:
        return 0.0
    if n < lo:
        return 0.6 + 0.4 * (n - MIN_PLAYLIST_TRACKS) / (lo - MIN_PLAYLIST_TRACKS)
    if n <= hi:
        return 1.0
    return max(0.3, hi / n)  # a 600-track dump is a weak statement per song


def _locality(distance: int) -> float:
    return max(LOCALITY_FLOOR, 0.5 ** (distance / LOCALITY_HALF_LIFE))


def _query_relevance(playlist: PlaylistInput, query_terms: set[str]) -> float:
    if not query_terms:
        return 1.0
    text = set(_fold(f"{playlist.name} {playlist.description}").split())
    overlap = len(query_terms & text) / len(query_terms)
    return 1.0 + 0.3 * overlap


def _anchor(playlist: PlaylistInput, seeds: list[Seed]) -> tuple[float, list[int]]:
    """(anchor weight, seed positions) for one playlist; weight 0 means drop it."""
    seed_keys = {(norm_title(s.title), norm_artist(s.artist)): s for s in seeds}
    seed_artists = {norm_artist(s.artist) for s in seeds}
    song_hits: dict[tuple[str, str], list[int]] = {}
    artist_positions: list[int] = []
    for t in playlist.tracks:
        title = norm_title(t["title"])
        artists = {norm_artist(a) for a in t["artists"]}
        matched = False
        for (stitle, sartist), _ in seed_keys.items():
            if title == stitle and sartist in artists:
                song_hits.setdefault((stitle, sartist), []).append(t["position"])
                matched = True
        if not matched and artists & seed_artists:
            artist_positions.append(t["position"])
    if song_hits:
        positions = [p for ps in song_hits.values() for p in ps]
        extra = min(MAX_EXTRA_SEED_BONUS, EXTRA_SEED_BONUS * (len(song_hits) - 1))
        return 1.0 + extra, positions
    if artist_positions:
        return ARTIST_ONLY_ANCHOR, artist_positions
    return 0.0, []


def score_candidates(
    playlists: list[PlaylistInput],
    seeds: list[Seed],
    query: str = "",
    *,
    editorial_weight: float = 0.25,
    min_owners: int = 2,
    limit: int = 40,
) -> list[ScoredCandidate]:
    """Rank songs that co-occur with the seeds across `playlists`. Seeds are excluded."""
    if not seeds or not playlists:
        return []
    query_terms = set(_fold(query).split())
    seed_keys = {(norm_title(s.title), norm_artist(s.artist)) for s in seeds}

    # Document frequency over every readable playlist: how common is a track generally?
    # Counted per distinct owner, like the support cap, so one person's many playlists
    # can't make a track look "common" (or "popular") by repetition.
    owners_of: dict[tuple[str, str], set[str]] = {}
    usable = [p for p in playlists if len(p.tracks) >= MIN_PLAYLIST_TRACKS]
    for p in usable:
        for key in {track_key(t["title"], t["artists"]) for t in p.tracks}:
            owners_of.setdefault(key, set()).add(p.owner_id)
    doc_freq = {key: len(owners) for key, owners in owners_of.items()}
    n_docs = len({p.owner_id for p in usable})

    # per track -> per owner -> best contribution (the owner cap)
    per_owner: dict[tuple[str, str], dict[str, float]] = {}
    meta: dict[tuple[str, str], dict] = {}
    playlist_hits: dict[tuple[str, str], int] = {}
    best_locality: dict[tuple[str, str], float] = {}
    examples: dict[tuple[str, str], list[str]] = {}

    for p in usable:
        anchor, centers = _anchor(p, seeds)
        if anchor == 0.0:
            continue
        owner_w = editorial_weight if p.owner_id == SPOTIFY_OWNER_ID else 1.0
        weight = anchor * owner_w * _size_factor(len(p.tracks)) * _query_relevance(p, query_terms)
        seen_in_playlist: set[tuple[str, str]] = set()
        for t in p.tracks:
            key = track_key(t["title"], t["artists"])
            if key in seed_keys or key in seen_in_playlist or not key[0]:
                continue
            seen_in_playlist.add(key)
            loc = _locality(min(abs(t["position"] - c) for c in centers))
            contribution = weight * loc
            owners = per_owner.setdefault(key, {})
            owners[p.owner_id] = max(owners.get(p.owner_id, 0.0), contribution)
            playlist_hits[key] = playlist_hits.get(key, 0) + 1
            best_locality[key] = max(best_locality.get(key, 0.0), loc)
            if len(examples.setdefault(key, [])) < 3 and p.name not in examples[key]:
                examples[key].append(p.name)
            meta.setdefault(key, t)

    scored: list[tuple[float, tuple[str, str]]] = []
    for key, owners in per_owner.items():
        rarity = 1.0 + math.log((n_docs + 1) / (doc_freq.get(key, 1) + 0.5))
        scored.append((sum(owners.values()) * rarity, key))
    if not scored:
        return []
    top = max(s for s, _ in scored)

    def build(raw: float, key: tuple[str, str], weak: bool) -> ScoredCandidate:
        t = meta[key]
        owners = per_owner[key]
        title = t["title"]
        return ScoredCandidate(
            title=title,
            artist=", ".join(t["artists"]),
            spotify_id=t.get("spotify_id"),
            url=t.get("url"),
            score=round(raw / top, 4),
            playlists=playlist_hits[key],
            owners=len(owners),
            user_owners=sum(1 for o in owners if o != SPOTIFY_OWNER_ID),
            best_locality=round(best_locality[key], 3),
            example_playlists=examples[key],
            variant_hint=(m.group(1).lower() if (m := _VARIANT.search(title)) else "original"),
            weak=weak,
        )

    seed_artists = {norm_artist(s.artist) for s in seeds}

    def cap_per_artist(ranked: list[ScoredCandidate]) -> list[ScoredCandidate]:
        counts: dict[str, int] = {}
        kept: list[ScoredCandidate] = []
        for c in ranked:
            artist = norm_artist(c.artist.split(", ")[0])
            cap = MAX_PER_SEED_ARTIST if artist in seed_artists else MAX_PER_ARTIST
            if counts.get(artist, 0) < cap:
                counts[artist] = counts.get(artist, 0) + 1
                kept.append(c)
        return kept

    strong = [build(r, k, False) for r, k in scored if len(per_owner[k]) >= min_owners]
    strong.sort(key=lambda c: c.score, reverse=True)
    strong = cap_per_artist(strong)
    if len(strong) >= min(limit, 10):
        return strong[:limit]
    weak = [build(r * 0.5, k, True) for r, k in scored if len(per_owner[k]) < min_owners]
    weak.sort(key=lambda c: c.score, reverse=True)
    return cap_per_artist(strong + weak)[:limit]
