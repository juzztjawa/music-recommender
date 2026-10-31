"""Pydantic request models for discovery endpoints."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class RetrievalRequest(BaseModel):
    hypothesis: str = Field(
        min_length=1,
        max_length=500,
        description="A search hypothesis describing what kind of songs to find",
    )
    include_live: bool = Field(
        default=False, description="Include live recordings (FR-10.4) — excluded by default"
    )
    include_covers: bool = Field(
        default=False,
        description="Include covers even when the original is also a candidate (FR-10.3)",
    )
    target_count: int = Field(
        default=10, ge=1, le=25, description="Final recommendation batch size (FR-11)"
    )


class AudioAnalysisRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="Input song to resolve and analyze, e.g. 'Bohemian Rhapsody Queen'",
    )


class DiscoverRequest(BaseModel):
    """Stateless request for the dev endpoints; real chats use `/chat/stream`."""


    message: Message = Field(
        description=(
            "What the user typed, as free text: song names, track links, a description of "
            "the music, or a follow-up to an earlier turn (FR-1.1, FR-1.3, FR-14)"
        )
    )
    include_live: bool = Field(
        default=False, description="Default for live recordings (FR-10.4); the message may override"
    )
    include_covers: bool = Field(
        default=False,
        description="Default for covers (FR-10.3); the message may override",
    )
    target_count: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Default batch size per theme (FR-11); the message may override",
    )
