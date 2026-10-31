"""Per-request working state shared by the supervisor's tools.

Large intermediate data (50-100 scored candidates with their evidence) lives
here, not in the model's context: tools hand the supervisor a compact summary
and a `cluster_id`, and later tools read the full data back from this object.
That keeps the context small and makes the deterministic stages (selection)
operate on the real data rather than on whatever the model re-typed.

The final `DiscoveryResult` is assembled from this state, never from model
output, so recommendations cannot be hallucinated into the response.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field

from app.schemas.audio import AudioAnalysisResult
from app.schemas.retrieval import Candidate
from app.services.threads import ThreadTurn


@dataclass
class ClusterState:
    theme: str
    hypothesis: str
    input_songs: list[str]
    candidates: list[Candidate] = field(default_factory=list)
    providers_queried: list[str] = field(default_factory=list)
    notes: str | None = None
    selected: list[Candidate] | None = None
    explanations: dict[str, str] | None = None


@dataclass
class RunContext:
    include_live: bool = False
    include_covers: bool = False
    target_count: int = 10
    # Earlier turns of this thread (FR-14) and the songs they recommended (FR-15).
    history: list[ThreadTurn] = field(default_factory=list)
    already_recommended: set[str] = field(default_factory=set)
    audio_results: list[AudioAnalysisResult] = field(default_factory=list)
    clusters: dict[str, ClusterState] = field(default_factory=dict)


# A ContextVar (not a global) so concurrent requests never share state;
# asyncio copies it into the tasks LangGraph spawns for parallel tool calls,
# and they all see the same mutable RunContext object.
current_run: ContextVar[RunContext | None] = ContextVar("current_run", default=None)


def require_run() -> RunContext:
    run = current_run.get()
    if run is None:
        raise RuntimeError("No active discovery run")
    return run
