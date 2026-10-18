"""Hypothesis models."""

from pydantic import BaseModel, Field


class HypothesisCluster(BaseModel):
    theme: str = Field(
        description="Short internal label for this cluster, e.g. the shared song or style"
    )
    songs: list[str] = Field(
        description="Which input song queries (verbatim) this cluster covers"
    )
    hypothesis: str = Field(
        description=(
            "A search-ready description of what kind of songs to find — this is handed "
            "directly to the Retrieval & Evidence Agent as its search hypothesis"
        )
    )


class HypothesisResult(BaseModel):
    clusters: list[HypothesisCluster]
