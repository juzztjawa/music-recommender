"""Discovery endpoints.

Phase 3 exposes the Retrieval & Evidence Agent directly, taking a hypothesis
string rather than a song — that's a deliberate shortcut so the agent is
live-testable before Query Understanding/Hypothesis Generation (Phase 6) and
Audio Analysis (Phase 5) exist to produce hypotheses from real input songs.
This route will be superseded by the full Orchestrator flow, not layered
under it.

Phase 4 adds consolidation/selection/diversification: the raw ~50-100 scored
candidates from the agent are reduced to the final presentable batch before
the response goes out.
"""

from fastapi import APIRouter, Depends

from app.agents.retrieval import RetrievalResult, run_retrieval
from app.api.deps import get_current_identity
from app.models.identity import Identity
from app.schemas.discovery import RetrievalRequest
from app.services.selection import select_recommendations

router = APIRouter()


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
