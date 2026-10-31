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

The real, conversational flow is `POST /chat/stream` (app/api/routes/chat.py).
The endpoints here are stateless dev/testing surfaces: `/discover*` runs the
supervisor agent on one message with no thread or memory, and `/retrieve` and
`/analyze-audio` run a single specialist.
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
from app.api.deps import enforce_discovery_rate_limit, get_current_identity, get_session_id
from app.models.identity import Identity
from app.observability import TraceContext
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


def _options(body: DiscoverRequest) -> dict[str, Any]:
    return {
        "include_live": body.include_live,
        "include_covers": body.include_covers,
        "target_count": body.target_count,
    }


@router.post("/discovery/discover", response_model=DiscoveryResult)
async def discover(
    body: DiscoverRequest,
    identity: Identity = Depends(get_current_identity),
    session_id: uuid.UUID | None = Depends(get_session_id),
) -> DiscoveryResult:
    run_id = uuid.uuid4()
    await log_event(identity.id, run_id, "query", body.model_dump(mode="json"))
    try:
        result = await run_discovery(
            body.message,
            trace=TraceContext(identity_id=identity.id, run_id=run_id, session_id=session_id),
            **_options(body),
        )
    except Exception as e:
        await log_event(identity.id, run_id, "error", {"message": str(e)})
        raise
    result.run_id = str(run_id)
    await log_event(identity.id, run_id, "recommendation", result.model_dump(mode="json"))
    return result


@router.post("/discovery/discover/stream")
async def discover_stream(
    body: DiscoverRequest,
    identity: Identity = Depends(get_current_identity),
    session_id: uuid.UUID | None = Depends(get_session_id),
) -> StreamingResponse:
    """Stateless streamed run (no thread). Events: `tool`, `message`, `result`, `error`."""
    run_id = uuid.uuid4()

    async def events() -> AsyncIterator[str]:
        await log_event(identity.id, run_id, "query", body.model_dump(mode="json"))
        try:
            async for event in stream_discovery(
                body.message,
                trace=TraceContext(identity_id=identity.id, run_id=run_id, session_id=session_id),
                **_options(body),
            ):
                if event["type"] == "result":
                    event["data"]["run_id"] = str(run_id)
                    await log_event(identity.id, run_id, "recommendation", event["data"])
                yield _sse(event)
        except Exception as e:
            logger.exception("Discovery stream failed")
            await log_event(identity.id, run_id, "error", {"message": str(e)})
            yield _sse({"type": "error", "message": "Discovery failed. Please try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
