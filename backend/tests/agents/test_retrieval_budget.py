"""The retrieval sub-agent must be bounded, and must not replay itself from scratch."""

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.agents import retrieval
from app.agents.tool_errors import handle_tool_errors, tool_budget
from app.schemas.retrieval import RetrievalResult


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool
async def search_demo(query: str) -> str:
    """demo search"""
    return f"results for {query}"


def search_call(i: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "search_demo", "args": {"query": f"q{i}"}, "id": str(i)}],
    )


async def test_calls_past_the_budget_are_not_executed_and_tell_the_agent_to_finish():
    model = ScriptedModel(
        responses=[search_call(1), search_call(2), search_call(3), AIMessage(content="done")]
    )
    agent = create_agent(
        model=model, tools=[search_demo], middleware=[tool_budget(2), handle_tool_errors]
    )

    result = await agent.ainvoke({"messages": [("user", "go")]}, config={"recursion_limit": 8})

    tool_results = [m for m in result["messages"] if m.type == "tool"]
    assert [m.status for m in tool_results] == ["success", "success", "error"]
    assert tool_results[0].content == "results for q1"
    assert "budget" in tool_results[2].content and "final" in tool_results[2].content


def test_recursion_limit_matches_configured_rounds(monkeypatch):
    monkeypatch.setattr(retrieval.settings, "retrieval_max_model_rounds", 8)
    assert retrieval._agent_config() == {"recursion_limit": 19}


def test_prompt_states_the_budget():
    assert "{max_tool_calls}" not in retrieval.SYSTEM_PROMPT
    assert str(retrieval.settings.retrieval_max_tool_calls) in retrieval.SYSTEM_PROMPT


async def test_failure_with_identical_primary_and_fallback_is_not_replayed(monkeypatch):
    monkeypatch.setattr(retrieval.settings, "ollama_primary_model", "same-model")
    monkeypatch.setattr(retrieval.settings, "ollama_fallback_model", "same-model")
    builds = []

    class Boom:
        async def ainvoke(self, *a, **k):
            raise TimeoutError("model read timeout")

    monkeypatch.setattr(retrieval, "_build_agent", lambda model: builds.append(1) or Boom())
    monkeypatch.setattr(retrieval, "get_primary_model", lambda: object())

    with pytest.raises(TimeoutError):
        await retrieval.run_retrieval("h")
    assert len(builds) == 1  # no second full search from scratch


async def test_failure_with_a_different_fallback_model_retries_once(monkeypatch):
    monkeypatch.setattr(retrieval.settings, "ollama_primary_model", "primary")
    monkeypatch.setattr(retrieval.settings, "ollama_fallback_model", "fallback")
    good = RetrievalResult(candidates=[], providers_queried=["x"])
    attempts = []

    class Flaky:
        def __init__(self, ok):
            self.ok = ok

        async def ainvoke(self, *a, **k):
            attempts.append(self.ok)
            if not self.ok:
                raise TimeoutError("boom")
            return {"structured_response": good}

    agents = iter([Flaky(False), Flaky(True)])
    monkeypatch.setattr(retrieval, "_build_agent", lambda model: next(agents))
    monkeypatch.setattr(retrieval, "get_primary_model", lambda: object())
    monkeypatch.setattr(retrieval, "get_fallback_model", lambda: object())

    assert await retrieval.run_retrieval("h") is good
    assert attempts == [False, True]
