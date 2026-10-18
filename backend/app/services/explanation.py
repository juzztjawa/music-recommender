"""Explanation Generation (FR-12).

A single, non-agentic structured-output LLM call — one call per cluster
covering its whole batch of selected candidates, not one call per song (that
would multiply LLM cost/latency for no benefit). Turns each candidate's
evidence into a human-readable explanation grounded in that evidence, per
FR-12: "always be defensible using collected evidence," never exposing
internal scores or provider mechanics as the explanation itself.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.retrieval import Candidate
from app.llm import run_structured
from app.resources import load_prompt

logger = logging.getLogger(__name__)


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


SYSTEM_PROMPT = load_prompt("explanation_system_prompt.txt")


def candidate_key(title: str, artist: str) -> str:
    return f"{title.strip().lower()}::{artist.strip().lower()}"


async def generate_explanations(
    hypothesis: str, candidates: list[Candidate]
) -> dict[str, str]:
    """Return `{candidate_key(title, artist): explanation}` for `candidates`.

    Callers should fall back to `Candidate.rationale` for any candidate
    missing from the result — the LLM isn't guaranteed to return a
    perfectly 1:1 matched list.
    """
    if not candidates:
        return {}

    lines = [f"Search hypothesis: {hypothesis}\n", "Candidates:"]
    for c in candidates:
        evidence_summary = "; ".join(f"[{e.source}] {e.summary}" for e in c.evidence)
        lines.append(f"- {c.title} by {c.artist} (variant: {c.variant}): {evidence_summary}")

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content="\n".join(lines))]

    try:
        result = await run_structured(messages, ExplanationResult)
    except Exception:
        logger.exception("Explanation generation failed for hypothesis %r", hypothesis)
        return {}

    return {
        candidate_key(e.title, e.artist): e.explanation for e in result.explanations
    }
