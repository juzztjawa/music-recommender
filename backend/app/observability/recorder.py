"""FR-19: record every LLM call and tool call of a run in `interaction_events`.

A LangChain callback handler, attached once at the top of the graph; LangChain
propagates it to every nested model/tool call (including the Retrieval agent's
tool loop), so agent code stays free of logging. Each call is written once,
when it finishes, with its duration. Like all logging here it must never break
the run: `log_event` swallows its own failures.
"""

import json
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage

from app.observability.context import TraceContext, current_stage
from app.services.interaction_log import log_event

_MAX_CHARS = 20_000


def clip(value: Any, limit: int = _MAX_CHARS) -> Any:
    """JSON-safe copy of `value`; oversized values become a marked preview."""
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= limit:
        return json.loads(text) if text else None
    return {"truncated": True, "chars": len(text), "preview": text[:limit]}


def _message_dict(m: BaseMessage) -> dict[str, Any]:
    return {"role": m.type, "content": m.content}


class TraceRecorder(AsyncCallbackHandler):
    def __init__(self, ctx: TraceContext) -> None:
        self.ctx = ctx
        self._started: dict[UUID, dict[str, Any]] = {}

    def _begin(self, run_id: UUID, **info: Any) -> None:
        self._started[run_id] = {"t0": time.monotonic(), "stage": current_stage.get(), **info}

    async def _finish(self, run_id: UUID, event_type: str, **payload: Any) -> None:
        info = self._started.pop(run_id, None)
        if info is None:
            return
        t0, stage = info.pop("t0"), info.pop("stage")
        await log_event(
            self.ctx.identity_id,
            self.ctx.run_id,
            event_type,
            {
                "stage": stage,
                "duration_ms": round((time.monotonic() - t0) * 1000),
                **info,
                **payload,
            },
        )

    # --- LLM calls ---

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        params = kwargs.get("invocation_params") or {}
        self._begin(
            run_id,
            model=params.get("model") or (serialized or {}).get("name"),
            prompt=clip([_message_dict(m) for m in messages[0]]),
        )

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        message = getattr(response.generations[0][0], "message", None)
        await self._finish(
            run_id,
            "llm_call",
            output=clip(message.content if message else response.generations[0][0].text),
            tool_calls=clip(getattr(message, "tool_calls", None) or []),
            usage=getattr(message, "usage_metadata", None),
            error=None,
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        await self._finish(run_id, "llm_call", error=f"{type(error).__name__}: {error}")

    # --- Tool calls ---

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._begin(
            run_id,
            tool=(serialized or {}).get("name") or kwargs.get("name"),
            args=clip(kwargs.get("inputs", input_str)),
        )

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = getattr(output, "content", output)
        await self._finish(run_id, "tool_call", result=clip(content), error=None)

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        await self._finish(run_id, "tool_call", error=f"{type(error).__name__}: {error}")
