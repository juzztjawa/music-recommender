"""Discovery endpoints.

Phase 3 exposes the Retrieval & Evidence Agent directly, taking a hypothesis
string rather than a song — that's a deliberate shortcut so the agent is
live-testable before Query Understanding/Hypothesis Generation (Phase 6) and
Audio Analysis (Phase 5) exist to produce hypotheses from real input songs.

Phase 4 adds consolidation/selection/diversification: the raw ~50-100 scored
candidates from the agent are reduced to the final presentable batch before
the response goes out.

Phase 5 adds the same kind of standalone test surface for the Audio Analysis
Agent, taking an input-song query rather than a hypothesis.

Phase 6 adds `/discovery/discover` — the real, full Orchestrator flow
(architecture.md §6): 1-5 input songs -> audio analysis -> hypothesis
generation -> retrieval -> selection -> explanation, in one call. `/retrieve`
and `/analyze-audio` remain as standalone test surfaces for their respective
agents, superseded but not removed.
"""

from fastapi import APIRouter, Depends

from app.agents.audio import analyze_input_song
from app.agents.orchestrator import DiscoveryResult, run_discovery
from app.agents.retrieval import run_retrieval
from app.api.deps import enforce_discovery_rate_limit, get_current_identity
from app.models.identity import Identity
from app.schemas.audio import AudioAnalysisResult
from app.schemas.discovery import AudioAnalysisRequest, DiscoverRequest, RetrievalRequest
from app.schemas.retrieval import RetrievalResult
from app.services.selection import select_recommendations

router = APIRouter(dependencies=[Depends(enforce_discovery_rate_limit)])


@router.post("/discovery/retrieve", response_model=RetrievalResult)
async def retrieve(
    body: RetrievalRequest,
    _identity: Identity = Depends(get_current_identity),
) -> RetrievalResult:
    result = await run_retrieval(body.hypothesis)
    result.candidates = select_recommendations(
        result.candidates,
        include_live=body.include_live,
        include_covers=body.include_covers,
        target_count=body.target_count,
    )
    return result


@router.post("/discovery/analyze-audio", response_model=AudioAnalysisResult)
async def analyze_audio(
    body: AudioAnalysisRequest,
    _identity: Identity = Depends(get_current_identity),
) -> AudioAnalysisResult:
    return await analyze_input_song(body.query)


@router.post("/discovery/discover", response_model=DiscoveryResult)
async def discover(
    body: DiscoverRequest,
    _identity: Identity = Depends(get_current_identity),
) -> DiscoveryResult:
    return await run_discovery(
        body.songs,
        include_live=body.include_live,
        include_covers=body.include_covers,
        target_count=body.target_count,
    )
