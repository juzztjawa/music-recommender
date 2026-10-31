"""The supervisor agent's tools (architecture.md §2/§3).

Each tool is one capability the supervisor can choose to use. The *order* in
which they are used is not here: it lives in the supervisor's system prompt
(`prompts/orchestrator_system_prompt.md`). Tools only enforce preconditions
(e.g. you cannot select from a cluster that was never retrieved) and return
compact results; bulky data stays in `RunContext`.
"""

from typing import Annotated
from urllib.parse import urlparse

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from app.agents.audio import analyze_input_song
from app.agents.explanation import candidate_key, generate_explanations
from app.agents.retrieval import run_retrieval
from app.agents.run_context import ClusterState, require_run
from app.clients.spotify import get_spotify_track, search_spotify
from app.clients.youtube_audio import get_youtube_metadata
from app.clients.youtube_music import search_youtube_music
from app.config import settings
from app.observability import current_stage
from app.services.selection import filter_excluded, filter_input_songs, select_recommendations
from app.services.threads import render_context

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "music.youtube.com")


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_youtube(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _YOUTUBE_HOSTS)


@tool
async def resolve_song(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=400,
            description="A song title/artist as the user wrote it, or a Spotify / YouTube / "
            "YouTube Music track URL",
        ),
    ],
) -> dict:
    """Identify a song: turn a title (and maybe artist) or a track URL into canonical
    title + artist metadata. Use it for every URL, and for song names that are vague."""
    current_stage.set("resolve_song")
    q = query.strip()
    if q.startswith(("http://", "https://")):
        host = _host(q)
        if host.endswith("spotify.com"):
            return await get_spotify_track(q)
        if _is_youtube(q):
            return await get_youtube_metadata(q)
        if host.endswith("apple.com"):
            return {"error": "Apple Music links are not supported; ask for title and artist."}
        return {"error": f"Unsupported link ({host}). Ask for the song title and artist."}

    matches: list[dict] = []
    errors: list[str] = []
    if settings.spotify_client_id and settings.spotify_client_secret:
        try:
            matches = (await search_spotify(q, 3))[:3]
        except Exception as e:  # noqa: BLE001 - fall through to the next provider
            errors.append(f"spotify: {e}")
    if not matches:
        try:
            matches = (await search_youtube_music(q, 3))[:3]
        except Exception as e:  # noqa: BLE001
            errors.append(f"youtube_music: {e}")
    keep = ("source", "title", "artist", "album")
    result: dict = {"matches": [{k: m.get(k) for k in keep} for m in matches]}
    if errors and not matches:
        result["error"] = "; ".join(errors)
    return result


@tool
async def analyze_audio(
    song: Annotated[
        str,
        Field(
            min_length=1,
            max_length=400,
            description="'<title> <artist>' of an INPUT song, or a YouTube track URL",
        ),
    ],
) -> dict:
    """Listen to an input song: find its audio on YouTube and produce a text description of
    instrumentation, tempo, mood and progression. Input songs only, never candidates.
    A failure (`error` set) is normal and not fatal: continue from the title alone."""
    current_stage.set("analyze_audio")
    if song.startswith(("http://", "https://")) and not _is_youtube(song):
        return {
            "query": song,
            "caption": None,
            "error": "Only YouTube links can be analysed; call resolve_song first and pass "
            "'<title> <artist>'.",
        }
    result = await analyze_input_song(song)
    require_run().audio_results.append(result)
    return result.model_dump()


@tool
async def get_session_history() -> dict:
    """What happened earlier in this conversation: previous user messages, what was said back, and
    the songs already recommended (with reasons for the latest ones). Call it first whenever the
    message could be a follow-up ("darker", "more like these", "something else", "hidden gems",
    "why did you pick the second one?")."""
    run = require_run()
    return {
        "conversation": render_context(run.history) or "(no earlier turns)",
        "already_recommended_count": len(run.already_recommended),
    }


@tool
async def retrieve_candidates(
    theme: Annotated[str, Field(min_length=1, max_length=80, description="Short label")],
    hypothesis: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description="Search-ready description of the kind of songs to find: mood, "
            "orchestration, pacing, texture, style, era — concrete enough to search on",
        ),
    ],
    input_songs: Annotated[
        list[str],
        Field(description="Input songs ('<title> <artist>') this cluster covers; [] if none"),
    ],
) -> dict:
    """Search the music sources for candidate songs matching one hypothesis (one cluster).
    Runs a retrieval specialist that queries Spotify, YouTube, YouTube Music, Reddit,
    MusicBrainz and Last.fm and scores each candidate on evidence. Returns a cluster_id
    and counts; the candidates themselves are held server-side."""
    current_stage.set("retrieve_candidates")
    run = require_run()
    cluster_id = f"c{len(run.clusters) + 1}"
    cluster = ClusterState(theme=theme, hypothesis=hypothesis, input_songs=list(input_songs))
    run.clusters[cluster_id] = cluster

    result = await run_retrieval(hypothesis)
    cluster.candidates = result.candidates
    cluster.providers_queried = result.providers_queried
    cluster.notes = result.notes
    return {
        "cluster_id": cluster_id,
        "candidates": len(result.candidates),
        "providers_queried": result.providers_queried,
        "notes": result.notes,
    }


def _cluster(cluster_id: str) -> ClusterState:
    cluster = require_run().clusters.get(cluster_id)
    if cluster is None:
        raise ValueError(
            f"Unknown cluster_id {cluster_id!r}; call retrieve_candidates first and use the "
            "cluster_id it returns."
        )
    return cluster


@tool
async def select_and_diversify(
    cluster_id: Annotated[str, Field(description="From retrieve_candidates")],
    include_live: Annotated[
        bool | None, Field(description="Only set if the user asked; else the default applies")
    ] = None,
    include_covers: Annotated[bool | None, Field(description="Same")] = None,
    target_count: Annotated[int | None, Field(ge=1, le=25, description="Same")] = None,
    allow_repeats: Annotated[
        bool, Field(description="True only if the user wants songs already recommended again")
    ] = False,
    exclude_artists: Annotated[
        list[str] | None,
        Field(description="Artists the user ruled out ('a different artist', 'not Hans Zimmer')"),
    ] = None,
) -> dict:
    """Apply the fixed selection rules to a cluster: merge duplicates, drop the input songs
    themselves, drop live/cover versions, rank by evidence strength, cap three per artist,
    skip songs already recommended in this conversation and any artists the user ruled out,
    trim to the target count. Fewer than
    requested is normal — never pad."""
    current_stage.set("select_and_diversify")
    run = require_run()
    cluster = _cluster(cluster_id)
    if not cluster.candidates:
        raise ValueError(f"Cluster {cluster_id} has no candidates; retrieval found nothing.")

    pool = filter_input_songs(cluster.candidates, cluster.input_songs)
    if not allow_repeats:
        pool = [c for c in pool if candidate_key(c.title, c.artist) not in run.already_recommended]
    if exclude_artists:
        pool = filter_excluded(pool, exclude_artists, [])
    cluster.selected = select_recommendations(
        pool,
        include_live=run.include_live if include_live is None else include_live,
        include_covers=run.include_covers if include_covers is None else include_covers,
        target_count=target_count or run.target_count,
    )
    return {
        "cluster_id": cluster_id,
        "selected": [
            {
                "title": c.title,
                "artist": c.artist,
                "strength": round(c.recommendation_strength, 2),
                "variant": c.variant,
            }
            for c in cluster.selected
        ],
        "note": None
        if cluster.selected
        else "Nothing survived selection. Say so honestly and suggest another reference song.",
    }


@tool
async def write_explanations(
    cluster_id: Annotated[str, Field(description="A cluster that has been selected")],
) -> dict:
    """Write the evidence-grounded explanation for each selected song in a cluster."""
    current_stage.set("write_explanations")
    cluster = _cluster(cluster_id)
    if cluster.selected is None:
        raise ValueError(f"Cluster {cluster_id} has not been through select_and_diversify.")
    cluster.explanations = await generate_explanations(cluster.hypothesis, cluster.selected)
    return {
        "cluster_id": cluster_id,
        "explained": len(cluster.explanations),
        "songs": len(cluster.selected),
    }


def orchestrator_tools() -> list[BaseTool]:
    return [
        resolve_song,
        analyze_audio,
        get_session_history,
        retrieve_candidates,
        select_and_diversify,
        write_explanations,
    ]
