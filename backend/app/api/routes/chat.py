"""Conversational interface: one free-text message in, a streamed assistant turn out.

`POST /chat/stream` hands the message and the thread's history to the supervisor
agent (`app.agents.orchestrator`), which decides for itself whether to search,
answer from the conversation, or both.

SSE events (`event: <type>\\ndata: <json>`):
  thread  {thread_id, run_id}                   first, always
  tool    {status, name, call_id, ...}          one started + one done/error per tool call
  message {text}                                the assistant's reply (also in result.data.reply)
  result  {data: DiscoveryResult}               always last on success; clusters may be empty
  error   {message, retry_after?}               failure; ends the stream
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import stream_discovery
from app.api.deps import (
    check_discovery_budget,
    enforce_chat_rate_limit,
    get_current_identity,
    get_db,
    get_redis,
    get_session_id,
)
from app.models.identity import Identity
from app.observability import TraceContext
from app.schemas.chat import ChatRequest, Thread, ThreadSummary
from app.services.interaction_log import log_event
from app.services.rate_limit import RateLimitExceeded
from app.services.threads import (
    get_thread,
    list_threads,
    load_history,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@router.get("/threads", response_model=list[ThreadSummary])
async def threads(
    identity: Identity = Depends(get_current_identity), db: AsyncSession = Depends(get_db)
) -> list[ThreadSummary]:
    return await list_threads(db, identity.id)


@router.get("/threads/{thread_id}", response_model=Thread)
async def thread(
    thread_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> Thread:
    found = await get_thread(db, identity.id, thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return found


# Tools that spend the shared YouTube / LLM budget. The discovery budget is
# charged when the supervisor first reaches for one, so a turn that only
# answers a question about earlier results doesn't use it up.
COSTLY_TOOLS = {"analyze_audio", "retrieve_candidates"}


@router.post("/chat/stream", dependencies=[Depends(enforce_chat_rate_limit)])
async def chat_stream(
    body: ChatRequest,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    session_id: uuid.UUID | None = Depends(get_session_id),
) -> StreamingResponse:
    thread_id = body.thread_id or uuid.uuid4()
    run_id = uuid.uuid4()
    # Loaded before streaming starts: the request-scoped session is closed
    # once the response generator is running.
    history = await load_history(db, identity.id, thread_id) if body.thread_id else []

    async def events() -> AsyncIterator[str]:
        yield _sse({"type": "thread", "thread_id": str(thread_id), "run_id": str(run_id)})
        await log_event(identity.id, run_id, "query", _query_payload(body, thread_id))
        budget_charged = False
        try:
            async with aclosing(
                stream_discovery(
                    body.message,
                    history=history,
                    include_live=bool(body.include_live),
                    include_covers=bool(body.include_covers),
                    target_count=body.target_count or 10,
                    trace=TraceContext(
                        identity_id=identity.id, run_id=run_id, session_id=session_id
                    ),
                )
            ) as stream:
                async for event in stream:
                    if (
                        event["type"] == "tool"
                        and event["status"] == "started"
                        and event["name"] in COSTLY_TOOLS
                        and not budget_charged
                    ):
                        budget_charged = True
                        await check_discovery_budget(redis, identity.id)
                    if event["type"] == "message":
                        await log_event(
                            identity.id, run_id, "assistant_message", {"text": event["text"]}
                        )
                    elif event["type"] == "result":
                        event["data"]["run_id"] = str(run_id)
                        event["data"]["thread_id"] = str(thread_id)
                        # Only real batches are stored as recommendations: history,
                        # feedback and export key off that event. A text-only answer
                        # is already stored as the assistant message.
                        if event["data"]["clusters"]:
                            await log_event(identity.id, run_id, "recommendation", event["data"])
                    yield _sse(event)
        except RateLimitExceeded as e:
            await log_event(identity.id, run_id, "error", {"message": "rate limited"})
            yield _sse(
                {
                    "type": "error",
                    "message": "Discovery limit reached.",
                    "retry_after": e.retry_after_seconds,
                }
            )
        except Exception as e:
            logger.exception("Chat turn failed")
            await log_event(identity.id, run_id, "error", {"message": str(e)})
            yield _sse({"type": "error", "message": "Something went wrong. Please try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _query_payload(body: ChatRequest, thread_id: uuid.UUID) -> dict[str, Any]:
    return {"thread_id": str(thread_id), "message": body.message, "songs": []}
