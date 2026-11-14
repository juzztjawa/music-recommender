"""Skills: task playbooks the supervisor loads on demand.

The supervisor's system prompt says *who it is and which kinds of request it
handles*; a skill holds the step-by-step *workflow* for one kind of request, so
the long recommendation pipeline is only in the model's context when a request
needs it. Layout: `app/skills/<name>/SKILL.md` with frontmatter `name` and
`description`. The system prompt lists name + description (`skill_index`); the
`load_skill` tool returns the body (`load_skill_body`).
"""

from pathlib import Path

from app.prompts import split_frontmatter

_DIR = Path(__file__).parent


def _skills() -> dict[str, tuple[dict[str, str], str]]:
    found = {}
    for path in sorted(_DIR.glob("*/SKILL.md")):
        meta, body = split_frontmatter(path.read_text())
        found[meta.get("name", path.parent.name)] = (meta, body)
    return found


def skill_index() -> str:
    """One line per skill for the system prompt."""
    return "\n".join(
        f"- {name}: {meta.get('description', '')}" for name, (meta, _) in _skills().items()
    )


def load_skill_body(name: str) -> str | None:
    skill = _skills().get(name)
    return skill[1] if skill else None


def skill_names() -> list[str]:
    return list(_skills())
