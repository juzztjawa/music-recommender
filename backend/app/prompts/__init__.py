"""LLM system prompts, one Markdown file per prompt.

Each file starts with a small YAML frontmatter block (`name`, `description`,
the same shape as a skill's SKILL.md) followed by the prompt text. The
frontmatter is for people: `load_prompt` strips it, so the model receives only
the body. Keeping prompts out of the Python lets them be read and edited without
touching code; git history is the version record.
"""

from pathlib import Path

_RESOURCES_DIR = Path(__file__).parent
_FENCE = "---"


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading `---` frontmatter block (flat `key: value` lines) from the body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _FENCE)
    except StopIteration:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1 :]).strip("\n")


def load_prompt(filename: str) -> str:
    """The prompt body (frontmatter removed, surrounding blank lines trimmed)."""
    return split_frontmatter((_RESOURCES_DIR / filename).read_text())[1]


def prompt_meta(filename: str) -> dict[str, str]:
    """The prompt's frontmatter: `name`, `description`."""
    return split_frontmatter((_RESOURCES_DIR / filename).read_text())[0]
