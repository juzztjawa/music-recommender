"""Explanation models."""

from pydantic import BaseModel, Field


class RecommendationExplanation(BaseModel):
    title: str
    artist: str
    explanation: str = Field(
        description=(
            "One or two human-readable sentences describing the strongest supporting "
            "evidence for this recommendation. Never mention internal scores, provider "
            "names as jargon, or implementation details — describe what the evidence "
            "actually shows, e.g. 'shares the same soaring orchestral builds' or "
            "'frequently recommended alongside your input song in fan discussions'."
        )
    )


class ExplanationResult(BaseModel):
    explanations: list[RecommendationExplanation]
