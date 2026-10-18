"""Static text resources (LLM system prompts) loaded at import time.

Keeping prompt text in its own package separates it from the orchestration
code that uses it, so prompts can be read/edited without touching Python.
"""

from pathlib import Path

_RESOURCES_DIR = Path(__file__).parent


def load_prompt(filename: str) -> str:
    """Read a prompt text file from this package, stripping the trailing newline."""
    return (_RESOURCES_DIR / filename).read_text().rstrip("\n")
