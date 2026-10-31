"""Prompts are Markdown with YAML frontmatter; the model must only see the body."""

from pathlib import Path

import pytest

from app import prompts

FILES = sorted(p.name for p in Path(prompts.__file__).parent.glob("*_prompt.md"))


def test_all_three_prompts_exist_and_none_are_left_as_txt():
    assert FILES == [
        "explanation_system_prompt.md",
        "orchestrator_system_prompt.md",
        "retrieval_system_prompt.md",
    ]
    assert not list(Path(prompts.__file__).parent.glob("*.txt"))


@pytest.mark.parametrize("filename", FILES)
def test_frontmatter_is_stripped_and_declared(filename):
    body, meta = prompts.load_prompt(filename), prompts.prompt_meta(filename)

    assert {"name", "version", "purpose"} <= meta.keys()
    assert meta["version"].isdigit()
    assert len(body) > 200
    assert not body.startswith("---")
    assert "version:" not in body.splitlines()[0]


def test_split_handles_missing_or_unclosed_frontmatter():
    assert prompts._split("just text") == ({}, "just text")
    assert prompts._split("---\nname: x\nno closing fence") == (
        {},
        "---\nname: x\nno closing fence",
    )
    assert prompts._split("---\nname: x\n---\n\nbody\n") == ({"name": "x"}, "body")


def test_orchestrator_prompt_still_carries_the_flow():
    body = prompts.load_prompt("orchestrator_system_prompt.md")
    stages = ("UNDERSTAND", "IDENTIFY", "LISTEN", "HYPOTHESISE", "RETRIEVE", "SELECT", "EXPLAIN")
    for stage in stages:
        assert stage in body
