"""Retrieval & Evidence Agent (architecture.md §2/§3).

A genuine tool-calling agent: it decides which of the 6 providers to query
and how extensively (FR-6.1/6.2), gathers evidence per candidate (FR-7), and
judges that evidence into a holistic recommendation-strength score (FR-9) —
all in one pass, so evidence only gets read once. Selection/diversification
against the scored output is deterministic Python and lives in Phase 4, not
here.

Tool schemas match `retrieval-agent-tool-schemas.json` (validated via the
agent-designer skill). A provider without configured credentials is simply
not offered as a tool — FR-6.1 already requires dynamic provider selection.

Built on `langchain.agents.create_agent`, not `langgraph.prebuilt.create_react_agent`
— the latter is deprecated as of LangGraph v1 (confirmed against the
installed langgraph==1.2.10/langchain==1.3.14 via the LangChain docs MCP).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.clients.lastfm import search_lastfm
from app.clients.musicbrainz import search_musicbrainz
from app.clients.reddit import search_reddit
from app.clients.spotify import search_spotify
from app.clients.youtube import search_youtube
from app.clients.youtube_music import search_youtube_music
from app.config import settings
from app.llm import get_fallback_model, get_primary_model
from app.resources import load_prompt

logger = logging.getLogger(__name__)

# --- Structured output schema (FR-7.1 provenance, FR-9 ranking) ---


class EvidenceItem(BaseModel):
    source: str = Field(description="Provider this evidence came from, e.g. 'spotify', 'reddit'")
    evidence_type: str = Field(
        description=(
            "Kind of evidence, e.g. 'metadata_similarity', 'community_discussion', "
            "'playlist_co_occurrence', 'genre_relationship', 'artist_relationship'"
        )
    )
    summary: str = Field(description="Human-readable description of what this evidence shows")


class Candidate(BaseModel):
    title: str
    artist: str
    sources: list[str] = Field(description="Providers that surfaced or corroborated this candidate")
    evidence: list[EvidenceItem]
    recommendation_strength: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Holistic strength per FR-9.2 — not probabilistic confidence. A single "
            "high-quality source can outscore several weak ones."
        ),
    )
    rationale: str = Field(description="Brief internal justification for the score")
    variant: Literal["original", "cover", "live", "remix"] = Field(
        default="original",
        description=(
            "Recording type per FR-10.3/10.4/10.5, judged from gathered evidence "
            "(release type, title conventions, discussion). 'original' unless "
            "evidence indicates otherwise."
        ),
    )


class RetrievalResult(BaseModel):
    candidates: list[Candidate]
    providers_queried: list[str]
    notes: str | None = Field(
        default=None, description="Caveats, e.g. providers skipped due to missing credentials"
    )


# --- Tools (one per provider, per retrieval-agent-tool-schemas.json) ---


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


# create_agent (v1) no longer catches tool exceptions by default — that was
# ToolNode's implicit behavior under the now-deprecated create_react_agent.
# Without this, a single provider hiccup (rate limit, network blip) would
# crash the whole retrieval run instead of just costing that one tool call.
#
# Must be async: run_retrieval invokes the agent via ainvoke(), and
# LangGraph's ToolNode requires an async awrap_tool_call implementation in an
# async run — a sync-only @wrap_tool_call raises NotImplementedError there
# (confirmed live), it isn't auto-adapted from sync.
@wrap_tool_call
async def _handle_tool_errors(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    try:
        return await handler(request)
    except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring above
        return ToolMessage(
            content=f"Tool error ({request.tool_call['name']}): {e}",
            tool_call_id=request.tool_call["id"],
        )


SYSTEM_PROMPT = load_prompt("retrieval_system_prompt.txt")


def _build_agent(model: BaseChatModel):
    # ToolStrategy generates structured output via tool-calling, in the main
    # loop — confirmed live that this model doesn't respect provider-native
    # structured output (the strategy create_agent would otherwise pick for
    # e.g. OpenAI/Anthropic), but its tool-calling is solid, which is the
    # whole premise of this agent anyway.
    return create_agent(
        model=model,
        tools=available_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=[_handle_tool_errors],
        response_format=ToolStrategy(RetrievalResult),
    )


class RetrievalFailedError(Exception):
    """Raised when neither model produces structured output for a hypothesis."""


async def run_retrieval(hypothesis: str) -> RetrievalResult:
    """Run the Retrieval & Evidence Agent against a single search hypothesis.

    Tries the primary model first, retrying once against the fallback model
    on failure — see app/llm.py for why this is a retry rather than
    LangChain's `.with_fallbacks()` (create_agent has the same `str |
    BaseChatModel` typing that rejected a fallback-wrapped runnable before).

    A "failure" here includes the agent completing its run without ever
    calling the structured-output tool — live-discovered: this model doesn't
    reliably honor structured output (the same reason app/llm.py's
    `run_structured` exists), and `ainvoke` returns a state dict with no
    `structured_response` key rather than raising in that case, so a missing
    key must be treated the same as a raised exception, not left to crash
    with a raw KeyError.
    """
    messages = {"messages": [HumanMessage(content=hypothesis)]}
    try:
        agent = _build_agent(get_primary_model())
        result = await agent.ainvoke(messages)
        if "structured_response" not in result:
            raise RetrievalFailedError("primary model produced no structured output")
    except Exception:
        logger.exception("Primary model failed for retrieval, retrying with fallback")
        agent = _build_agent(get_fallback_model())
        result = await agent.ainvoke(messages)
        if "structured_response" not in result:
            raise RetrievalFailedError("fallback model produced no structured output") from None
    return result["structured_response"]
