"""Retrieval/candidate models shared by agents, services and routes (FR-7.1, FR-9)."""

from typing import Literal

from pydantic import BaseModel, Field


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
