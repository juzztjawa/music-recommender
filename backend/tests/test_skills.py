"""Skills are listed in the supervisor's prompt and loaded on demand."""

import pytest

from app.agents import orchestrator
from app.skills import load_skill_body, skill_index, skill_names
from app.tools.orchestrator import load_skill, orchestrator_tools


def test_recommendation_skill_is_discoverable_and_has_the_workflow():
    assert "recommendation" in skill_names()
    assert "recommendation:" in skill_index()
    body = load_skill_body("recommendation")
    assert body and "retrieve_candidates" in body and "select_and_diversify" in body
    assert not body.startswith("---")  # frontmatter stripped


def test_system_prompt_lists_skills_but_not_the_workflow():
    prompt = orchestrator.SYSTEM_PROMPT
    assert "{skills}" not in prompt
    assert "- recommendation:" in prompt
    assert "select_and_diversify" not in prompt  # lives in the skill, loaded on demand


async def test_load_skill_tool_returns_the_body():
    assert await load_skill.ainvoke({"name": "recommendation"}) == load_skill_body("recommendation")


async def test_load_skill_rejects_unknown_names_with_the_available_ones():
    with pytest.raises(ValueError, match="recommendation"):
        await load_skill.ainvoke({"name": "nope"})


def test_load_skill_is_offered_to_the_supervisor():
    assert "load_skill" in [t.name for t in orchestrator_tools()]


def test_prompt_routes_each_kind_of_request():
    prompt = orchestrator.SYSTEM_PROMPT
    for marker in (
        "<role>",
        "<constraints>",
        "<instructions>",
        "<output_format>",
        "<examples>",
        "`load_skill` with `recommendation`",
        "`analyze_audio`",
        "`get_session_history`",
    ):
        assert marker in prompt
