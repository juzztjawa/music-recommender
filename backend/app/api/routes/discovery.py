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

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agents.audio import analyze_input_song
from app.agents.orchestrator import DiscoveryResult, run_discovery, stream_discovery
from app.agents.retrieval import run_retrieval
from app.api.deps import enforce_discovery_rate_limit, get_current_identity
from app.models.identity import Identity
from app.schemas.audio import AudioAnalysisResult
from app.schemas.discovery import AudioAnalysisRequest, DiscoverRequest, RetrievalRequest
from app.schemas.retrieval import RetrievalResult
from app.services.interaction_log import log_event
from app.services.selection import select_recommendations

logger = logging.getLogger(__name__)

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


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@router.post("/discovery/discover", response_model=DiscoveryResult)
async def discover(
    body: DiscoverRequest,
    identity: Identity = Depends(get_current_identity),
) -> DiscoveryResult:
    run_id = uuid.uuid4()
    await log_event(identity.id, run_id, "query", body.model_dump())
    try:
        result = await run_discovery(
            body.songs,
            include_live=body.include_live,
            include_covers=body.include_covers,
            target_count=body.target_count,
        )
    except Exception as e:
        await log_event(identity.id, run_id, "error", {"message": str(e)})
        raise
    await log_event(identity.id, run_id, "recommendation", result.model_dump(mode="json"))
    return result


@router.post("/discovery/discover/stream")
async def discover_stream(
    body: DiscoverRequest,
    identity: Identity = Depends(get_current_identity),
) -> StreamingResponse:
    """Same flow as `/discover`, streamed as Server-Sent Events: `step`
    (started/done per stage), then `result`, or `error`. Every event is also
    written to the FR-19 interaction log as it is emitted."""
    run_id = uuid.uuid4()

    async def events() -> AsyncIterator[str]:
        await log_event(identity.id, run_id, "query", body.model_dump())
        try:
            async for event in stream_discovery(
                body.songs,
                include_live=body.include_live,
                include_covers=body.include_covers,
                target_count=body.target_count,
            ):
                await log_event(
                    identity.id,
                    run_id,
                    "recommendation" if event["type"] == "result" else "step",
                    event,
                )
                yield _sse(event)
        except Exception as e:
            logger.exception("Discovery stream failed")
            error = {"type": "error", "message": "Discovery failed. Please try again."}
            await log_event(identity.id, run_id, "error", {"message": str(e)})
            yield _sse(error)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
