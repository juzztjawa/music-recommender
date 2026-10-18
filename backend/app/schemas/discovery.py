"""Pydantic request models for discovery endpoints."""

from pydantic import BaseModel, Field


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
    songs: list[str] = Field(
        min_length=1,
        max_length=5,
        description="1-5 input songs, e.g. ['Bohemian Rhapsody Queen'] (FR-1.2)",
    )
    include_live: bool = Field(
        default=False, description="Include live recordings (FR-10.4) — excluded by default"
    )
    include_covers: bool = Field(
        default=False,
        description="Include covers even when the original is also a candidate (FR-10.3)",
    )
    target_count: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Final recommendation batch size per cluster (FR-11)",
    )
