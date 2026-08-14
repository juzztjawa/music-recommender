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

from langchain_ollama import ChatOllama

from app.config import settings


def _build_model(model_name: str) -> ChatOllama:
    client_kwargs: dict = {}
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
