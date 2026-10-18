"""Retrieval Agent tools — one LangChain tool per provider client, per
`retrieval-agent-tool-schemas.json`. Tools only wrap `app.clients`; the agent
that decides when to call them lives in `app.agents.retrieval`."""

from typing import Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from app.clients.lastfm import search_lastfm
from app.clients.musicbrainz import search_musicbrainz
from app.clients.reddit import search_reddit
from app.clients.spotify import search_spotify
from app.clients.youtube import search_youtube
from app.clients.youtube_music import search_youtube_music
from app.config import settings


@tool
async def search_spotify_tool(
    query: Annotated[str, Field(min_length=1, max_length=300, description="Search text")],
    limit: Annotated[int, Field(ge=1, le=50, description="Max results")] = 20,
) -> list[dict]:
    """Search Spotify's catalog for candidate tracks matching a query or seed characteristics."""
    return await search_spotify(query, limit)


@tool
async def search_youtube_tool(
    query: Annotated[str, Field(min_length=1, max_length=300, description="Search text")],
    limit: Annotated[int, Field(ge=1, le=25, description="Max results")] = 10,
) -> list[dict]:
    """Search YouTube for candidate tracks and community signal (views, comment counts)."""
    return await search_youtube(query, limit)


@tool
async def search_youtube_music_tool(
    query: Annotated[str, Field(min_length=1, max_length=300, description="Search text")],
    limit: Annotated[int, Field(ge=1, le=25, description="Max results")] = 15,
) -> list[dict]:
    """Search YouTube Music for candidate tracks via the unofficial ytmusicapi client."""
    return await search_youtube_music(query, limit)


@tool
async def search_reddit_tool(
    query: Annotated[str, Field(min_length=1, max_length=300, description="Search text")],
    subreddits: Annotated[
        list[str] | None, Field(description="Optional subreddit allowlist to scope the search")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=30, description="Max results")] = 15,
) -> list[dict]:
    """Search Reddit for community discussion evidence: threads and curated playlist mentions."""
    return await search_reddit(query, subreddits, limit)


@tool
async def search_musicbrainz_tool(
    query: Annotated[
        str, Field(min_length=1, max_length=300, description="Title/artist to resolve")
    ],
) -> list[dict]:
    """Resolve authoritative metadata and relationships for a candidate track."""
    return await search_musicbrainz(query)


@tool
async def search_lastfm_tool(
    artist: Annotated[str, Field(min_length=1, max_length=200, description="Artist name")],
    track: Annotated[str | None, Field(max_length=200, description="Track title")] = None,
) -> dict:
    """Fetch tag/genre data and similar-artist signal for a candidate track from Last.fm."""
    return await search_lastfm(artist, track)


def available_tools() -> list[BaseTool]:
    """Tools for providers with configured credentials. MusicBrainz and YouTube
    Music need none, so they're always available."""
    tools: list[BaseTool] = [search_musicbrainz_tool, search_youtube_music_tool]
    if settings.spotify_client_id and settings.spotify_client_secret:
        tools.append(search_spotify_tool)
    if settings.youtube_api_key:
        tools.append(search_youtube_tool)
    if settings.reddit_client_id and settings.reddit_client_secret:
        tools.append(search_reddit_tool)
    if settings.lastfm_api_key:
        tools.append(search_lastfm_tool)
    return tools
