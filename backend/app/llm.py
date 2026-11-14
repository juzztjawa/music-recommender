"""Shared Ollama Cloud chat-model factory.

Lives alongside db.py/redis.py rather than in app/clients/ — this is the
reasoning substrate every agent depends on (Orchestrator, Retrieval &
Evidence, Explanation), not a narrow data-provider adapter.

Since Ollama Cloud's interface is identical across `:cloud` models
(architecture.md §4), primary/fallback is a config change, not a code one.
`get_primary_model()`/`get_fallback_model()` are exposed separately, rather
than composed via LangChain's `.with_fallbacks()`, because
`create_react_agent`'s `response_format` structured-output step requires a
plain `BaseChatModel` — a `RunnableWithFallbacks` fails its type check
(confirmed: `TypeError: Expected model to be a ChatModel or RunnableBinding`).
Callers implement fallback as a retry around the whole agent call instead;
see `app/agents/retrieval.py`.
"""

import logging
from typing import cast

import httpx
from langchain_core.messages import BaseMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


def _build_model(model_name: str) -> ChatOllama:
    # client_kwargs is passed straight through to the underlying httpx
    # client (ollama.Client/AsyncClient). ChatOllama streams, so `read` is the
    # gap between chunks, not the call's total duration; None (default) disables
    # it because a reasoning model can be silent for minutes before token one.
    # Only connecting is bounded, so an unreachable server still fails fast.
    client_kwargs: dict = {
        "timeout": httpx.Timeout(
            connect=settings.ollama_connect_timeout_seconds,
            read=settings.ollama_request_timeout_seconds,
            write=30.0,
            pool=None,
        )
    }
    if settings.ollama_api_key:
        client_kwargs["headers"] = {"Authorization": f"Bearer {settings.ollama_api_key}"}

    return ChatOllama(
        model=model_name,
        base_url=settings.ollama_base_url,
        client_kwargs=client_kwargs,
    )


def get_primary_model() -> ChatOllama:
    return _build_model(settings.ollama_primary_model)


def get_fallback_model() -> ChatOllama:
    return _build_model(settings.ollama_fallback_model)


async def run_structured[T: BaseModel](messages: list[BaseMessage], schema: type[T]) -> T:
    """Single non-agentic structured-output call (Hypothesis Generation,
    Explanation Generation) — no tool loop, just a direct model invocation.

    Tries the primary model, retrying once against the fallback on failure,
    same pattern as `app/agents/retrieval.py`'s `run_retrieval`.
    `method="function_calling"`: confirmed live (see retrieval.py's docstring
    history) that the installed Ollama Cloud model doesn't reliably honor
    `with_structured_output`'s default `json_schema` method.
    """
    try:
        model = get_primary_model()
        result = await model.with_structured_output(schema, method="function_calling").ainvoke(
            messages
        )
    except Exception:
        logger.exception("Primary model failed for structured call, retrying with fallback")
        model = get_fallback_model()
        result = await model.with_structured_output(schema, method="function_calling").ainvoke(
            messages
        )
    if isinstance(result, dict):
        return schema.model_validate(result)
    return cast(T, result)
