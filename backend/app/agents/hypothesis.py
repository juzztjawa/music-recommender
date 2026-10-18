"""Query Understanding + Hypothesis Generation (FR-2, FR-4, FR-1.2).

A single, non-agentic structured-output LLM call — no tool loop, unlike the
Retrieval & Evidence Agent. Takes the input songs (plus their audio captions,
when available) and produces one or more search hypotheses for the Retrieval
& Evidence Agent to act on.

FR-1.2: when the input songs are stylistically divergent, this clusters them
into separate per-theme hypotheses rather than forcing one blended
interpretation — and never asks the user to clarify or prioritize (low
user effort takes precedence over disambiguation, per FR-1.2's own wording).
FR-2's internal intent representation is implementation-defined and never
exposed to users — `HypothesisCluster.theme`/`hypothesis` are that
representation, not user-facing copy.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import run_structured
from app.prompts import load_prompt
from app.schemas.audio import AudioAnalysisResult
from app.schemas.hypothesis import HypothesisResult

SYSTEM_PROMPT = load_prompt("hypothesis_system_prompt.txt")


async def generate_hypotheses(
    songs: list[str], audio_results: list[AudioAnalysisResult]
) -> HypothesisResult:
    """Turn `songs` (free-text queries) + their `audio_results` (same order,
    same length) into one or more search hypotheses."""
    lines = ["Input songs:\n"]
    for query, audio in zip(songs, audio_results, strict=True):
        lines.append(f"- Query: {query!r}")
        if audio.caption:
            lines.append(f"  Audio caption: {audio.caption}")
        else:
            lines.append(f"  Audio caption: unavailable ({audio.error})")
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content="\n".join(lines))]
    return await run_structured(messages, HypothesisResult)
