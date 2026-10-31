"""Orchestrator — the Supervisor (architecture.md §2/§3).

A tool-calling agent. It receives the user's message (free text, links,
descriptions, follow-ups) plus the thread's history, and decides which tools to
call. The stage order — understand, identify, listen, hypothesise, retrieve,
select, explain, reply — is written in its system prompt
(`prompts/orchestrator_system_prompt.md`), not hardcoded here; the tools
(`app/tools/orchestrator.py`) enforce preconditions and keep the bulky data in
a per-request `RunContext`.

The `DiscoveryResult` is assembled from that state, never from the model's
text, so the recommendations shown are exactly what the deterministic stages
produced. The model's final message is only the conversational `reply`.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from app.agents.explanation import candidate_key
from app.agents.run_context import ClusterState, RunContext, current_run
from app.agents.tool_errors import handle_tool_errors
from app.config import settings
from app.llm import get_fallback_model, get_primary_model
from app.observability import TraceContext, TraceRecorder, root_span
from app.prompts import load_prompt
from app.schemas.audio import AudioAnalysisResult
from app.schemas.retrieval import EvidenceItem
from app.services.threads import ThreadTurn
from app.tools.orchestrator import orchestrator_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = load_prompt("orchestrator_system_prompt.md")

# --- Output shape ---


class RecommendedSong(BaseModel):
    title: str
    artist: str
    sources: list[str]
    evidence: list[EvidenceItem]
    recommendation_strength: float
    variant: str
    explanation: str


class DiscoveryCluster(BaseModel):
    theme: str
    hypothesis: str
    input_songs: list[str]
    recommendations: list[RecommendedSong]


class DiscoveryResult(BaseModel):
    # Set by the route that logs the run; feedback and export refer to run_id.
    run_id: str | None = None
    thread_id: str | None = None
    # The supervisor's conversational message (what it understood / what it did).
    reply: str = ""
    audio_analysis: list[AudioAnalysisResult]
    clusters: list[DiscoveryCluster]


# --- Helpers ---


def _text(content: Any) -> str:
    """Message content is a str or a list of blocks, depending on the provider."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def _cluster_result(cluster: ClusterState) -> DiscoveryCluster:
    explanations = cluster.explanations or {}
    return DiscoveryCluster(
        theme=cluster.theme,
        hypothesis=cluster.hypothesis,
        input_songs=cluster.input_songs,
        recommendations=[
            RecommendedSong(
                title=c.title,
                artist=c.artist,
                sources=c.sources,
                evidence=c.evidence,
                recommendation_strength=c.recommendation_strength,
                variant=c.variant,
                # The agent's own rationale if the explanation call failed or skipped a song.
                explanation=explanations.get(candidate_key(c.title, c.artist), c.rationale),
            )
            for c in cluster.selected or []
        ],
    )


def assemble_result(run: RunContext, reply: str) -> DiscoveryResult:
    # Only clusters that went through selection count; a retrieval the agent
    # never finished is not a recommendation.
    clusters = [_cluster_result(c) for c in run.clusters.values() if c.selected is not None]
    if not reply.strip():
        reply = (
            "Here is what I found."
            if any(c.recommendations for c in clusters)
            else "I couldn't put together recommendations with enough evidence this time. "
            "Could you tell me another song you like, or describe the feel you want?"
        )
    return DiscoveryResult(reply=reply, audio_analysis=run.audio_results, clusters=clusters)


def _user_input(message: str, run: RunContext) -> dict[str, list]:
    lines = [
        f"User message: {message}",
        f"Defaults (apply unless the message says otherwise): include_live={run.include_live}, "
        f"include_covers={run.include_covers}, target_count={run.target_count}.",
    ]
    if run.history:
        lines.append(
            f"This thread has {len(run.history)} earlier turn(s); call get_session_history if the "
            "message may refer to them."
        )
    return {"messages": [HumanMessage(content="\n".join(lines))]}


def _build_agent(model):
    return create_agent(
        model=model,
        tools=orchestrator_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=[handle_tool_errors],
    )


def _config(trace: TraceContext | None) -> dict[str, Any]:
    config: dict[str, Any] = {"recursion_limit": settings.agent_recursion_limit}
    if trace:
        config["callbacks"] = [TraceRecorder(trace)]
    return config


def _brief(content: Any, limit: int = 200) -> str:
    text = _text(content) if not isinstance(content, str) else content
    return text if len(text) <= limit else text[:limit] + "…"


# --- Streaming ---


async def stream_discovery(
    message: str,
    *,
    history: list[ThreadTurn] | None = None,
    include_live: bool = False,
    include_covers: bool = False,
    target_count: int = 10,
    trace: TraceContext | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the supervisor and yield events as it works:

    - ``tool`` started/done/error, one pair per tool call (a ``call_id`` links them)
    - ``message`` the supervisor's final reply
    - ``result`` the assembled `DiscoveryResult`

    Errors propagate to the caller, which turns them into an ``error`` event.
    """
    history = history or []
    run = RunContext(
        include_live=include_live,
        include_covers=include_covers,
        target_count=target_count,
        history=history,
        already_recommended={
            candidate_key(title, artist)
            for turn in history
            for title, artist, _ in turn.recommended
        },
    )
    queue: asyncio.Queue[dict | Exception | None] = asyncio.Queue()

    # The agent runs in its own task so the MLflow root span opens and closes
    # in one task (it can't stay open across this generator's yields), and so
    # `current_run` is set in a context the tools' tasks inherit.
    async def produce() -> None:
        current_run.set(run)
        emitted = False
        try:
            with root_span(trace, message):
                for attempt, get_model in enumerate((get_primary_model, get_fallback_model)):
                    try:
                        agent = _build_agent(get_model())
                        async for chunk in agent.astream(
                            _user_input(message, run),
                            config=_config(trace),
                            stream_mode="updates",
                        ):
                            emitted = True
                            await queue.put(chunk)
                        break
                    except Exception:
                        # Retry on the fallback model only if nothing has run yet;
                        # replaying a half-finished run would repeat its tool calls.
                        if emitted or attempt == 1:
                            raise
                        logger.exception("Primary model failed before any output; trying fallback")
        except Exception as e:  # noqa: BLE001 - handed to the consumer to re-raise
            await queue.put(e)
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    limit = settings.discovery_timeout_seconds
    deadline = time.monotonic() + limit if limit else None
    started: dict[str, float] = {}
    reply = ""
    timed_out = False
    try:
        while True:
            try:
                if deadline is None:
                    chunk = await queue.get()
                else:
                    remaining = max(deadline - time.monotonic(), 0.001)
                    chunk = await asyncio.wait_for(queue.get(), timeout=remaining)
            except TimeoutError:
                timed_out = True
                break
            if chunk is None:
                break
            if isinstance(chunk, Exception):
                raise chunk
            for update in chunk.values():
                for msg in update.get("messages", []) if isinstance(update, dict) else []:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            started[call["id"]] = time.monotonic()
                            yield {
                                "type": "tool",
                                "status": "started",
                                "name": call["name"],
                                "call_id": call["id"],
                                "args": call["args"],
                            }
                        if not msg.tool_calls:
                            reply = _text(msg.content)
                    elif isinstance(msg, ToolMessage):
                        t0 = started.pop(msg.tool_call_id, time.monotonic())
                        yield {
                            "type": "tool",
                            "status": "error" if msg.status == "error" else "done",
                            "name": msg.name,
                            "call_id": msg.tool_call_id,
                            "duration_ms": round((time.monotonic() - t0) * 1000),
                            "summary": _brief(msg.content),
                        }
    finally:
        producer.cancel()

    if timed_out:
        # Never fail silently: say what happened and keep whatever finished.
        reply = (
            "This is taking longer than the time limit allows, so I stopped here. "
            "Try again, or ask for something narrower."
        )
    result = assemble_result(run, reply)
    yield {"type": "message", "text": result.reply}
    yield {"type": "result", "data": result.model_dump(mode="json")}


async def run_discovery(message: str, **kwargs: Any) -> DiscoveryResult:
    """Same run as `stream_discovery`, returning only the final result."""
    result: DiscoveryResult | None = None
    async for event in stream_discovery(message, **kwargs):
        if event["type"] == "result":
            result = DiscoveryResult.model_validate(event["data"])
    assert result is not None  # stream_discovery always ends with a result or raises
    return result
