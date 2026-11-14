"""Retrieval & Evidence Agent (architecture.md §2/§3).

A genuine tool-calling agent: it decides which of the 6 providers to query
and how extensively (FR-6.1/6.2), gathers evidence per candidate (FR-7), and
judges that evidence into a holistic recommendation-strength score (FR-9) —
all in one pass, so evidence only gets read once. Selection/diversification
against the scored output is deterministic Python and lives in Phase 4, not
here.

Tool schemas match `retrieval-agent-tool-schemas.json` (validated via the
agent-designer skill). A provider without configured credentials is simply
not offered as a tool — FR-6.1 already requires dynamic provider selection.

Built on `langchain.agents.create_agent`, not `langgraph.prebuilt.create_react_agent`
— the latter is deprecated as of LangGraph v1 (confirmed against the
installed langgraph==1.2.10/langchain==1.3.14 via the LangChain docs MCP).
"""

import logging

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.agents.tool_errors import handle_tool_errors, tool_budget
from app.config import settings
from app.llm import get_fallback_model, get_primary_model
from app.prompts import load_prompt
from app.schemas.retrieval import RetrievalResult
from app.tools.retrieval import available_tools

logger = logging.getLogger(__name__)

# --- Structured output schema (FR-7.1 provenance, FR-9 ranking) ---


SYSTEM_PROMPT = (
    load_prompt("retrieval_system_prompt.md")
    .replace("{max_tool_calls}", str(settings.retrieval_max_tool_calls))
    .replace("{max_model_rounds}", str(settings.retrieval_max_model_rounds))
    .replace("{max_reddit_searches}", str(settings.retrieval_max_reddit_searches))
    .replace("{max_reddit_threads}", str(settings.retrieval_max_reddit_threads))
)


def _build_agent(model: BaseChatModel):
    # ToolStrategy generates structured output via tool-calling, in the main
    # loop — confirmed live that this model doesn't respect provider-native
    # structured output (the strategy create_agent would otherwise pick for
    # e.g. OpenAI/Anthropic), but its tool-calling is solid, which is the
    # whole premise of this agent anyway.
    return create_agent(
        model=model,
        tools=available_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            tool_budget(
                settings.retrieval_max_tool_calls,
                per_tool={
                    "search_reddit_tool": settings.retrieval_max_reddit_searches,
                    "read_reddit_thread_tool": settings.retrieval_max_reddit_threads,
                },
            ),
            handle_tool_errors,
        ],
        response_format=ToolStrategy(RetrievalResult),
    )


class RetrievalFailedError(Exception):
    """Raised when neither model produces structured output for a hypothesis."""


def _agent_config() -> dict:
    # One round = a model step + a tools step; +3 leaves room for the final answer.
    return {"recursion_limit": 2 * settings.retrieval_max_model_rounds + 3}


async def run_retrieval(
    hypothesis: str, input_songs: list[str] | None = None
) -> RetrievalResult:
    """Run the Retrieval & Evidence Agent against a single search hypothesis.

    Bounded by a tool-call budget and a round limit (see config). If the
    primary model fails and a *different* fallback model is configured, the
    run is retried once on it — see app/llm.py for why this is a retry rather
    than LangChain's `.with_fallbacks()`. When primary and fallback are the
    same model there is nothing to fall back to: retrying would only replay the
    whole search from zero (live, that doubled a run's duration), so the error
    is raised instead.

    A "failure" here includes the agent completing its run without ever
    calling the structured-output tool — live-discovered: this model doesn't
    reliably honor structured output (the same reason app/llm.py's
    `run_structured` exists), and `ainvoke` returns a state dict with no
    `structured_response` key rather than raising in that case, so a missing
    key must be treated the same as a raised exception, not left to crash
    with a raw KeyError.
    """
    content = hypothesis
    if input_songs:
        content += "\n\nInput songs for this cluster (title and artist):\n" + "\n".join(
            f"- {song}" for song in input_songs
        )
    messages = {"messages": [HumanMessage(content=content)]}
    try:
        agent = _build_agent(get_primary_model())
        result = await agent.ainvoke(messages, config=_agent_config())
        if "structured_response" not in result:
            raise RetrievalFailedError("primary model produced no structured output")
    except Exception:
        if settings.ollama_fallback_model == settings.ollama_primary_model:
            raise
        logger.exception("Primary model failed for retrieval, retrying with fallback")
        agent = _build_agent(get_fallback_model())
        result = await agent.ainvoke(messages, config=_agent_config())
        if "structured_response" not in result:
            raise RetrievalFailedError("fallback model produced no structured output") from None
    return result["structured_response"]
