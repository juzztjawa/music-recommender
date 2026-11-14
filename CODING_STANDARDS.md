# Coding standards

The goal: a codebase a stranger can read top to bottom and learn from. Not "it runs", but "it is
clear, consistent and tested". Read this before writing or changing code, whether you are a person or an AI
assistant. When this file and a quick fix disagree, this file wins; when this file is silent, follow the
references below instead of inventing a style.

## 1. References (the standard, not our opinion)

| Topic | Source |
|---|---|
| Style, imports, naming, layout | [PEP 8](https://peps.python.org/pep-0008/) |
| Docstrings | [PEP 257](https://peps.python.org/pep-0257/) |
| Type hints | [PEP 484](https://peps.python.org/pep-0484/) and the `typing` docs |
| Design principles | [PEP 20 (Zen of Python)](https://peps.python.org/pep-0020/) |
| Everything PEP 8 leaves open | [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) |
| Lint / format rules we enforce | [Ruff](https://docs.astral.sh/ruff/rules/) (config in each `pyproject.toml`) |
| Dependencies and lockfiles | [uv](https://docs.astral.sh/uv/) |
| Config and secrets in the environment | [The Twelve-Factor App](https://12factor.net/config) |
| Modal (GPU endpoint) | [Images](https://modal.com/docs/guide/images), [Lifecycle hooks](https://modal.com/docs/guide/lifecycle-functions) |

## 2. Imports

PEP 8: imports go **at the top of the file**, after the module docstring and before module constants,
in three groups separated by a blank line: standard library, third party, this project. Absolute imports,
no `from x import *`. Ruff's `I` rules sort them; run `ruff check --fix`.

### When a function-level (lazy) import is allowed

Only for the cases below, and every one gets a one-line comment naming the case. Anything else is a bug.

1. **Optional dependency.** The feature works without the package, and the import sits inside the code path
   that needs it (for example an exporter that is only used when a flag is set).
2. **Circular import** that cannot be removed by moving code. Prefer moving the shared piece into a third
   module; a lazy import is the last resort.
3. **Heavy import on a rarely used path** of a command-line tool, where start-up time is user-visible.
4. **The package only exists in a remote runtime.** Do not use function-level imports here; use the
   framework's mechanism (for Modal: `with image.imports():`, see section 3).

Not allowed: lazy imports to make a badly split module importable. If importing a file drags in a library
the importer does not have, **split the file**: keep the light code (constants, helpers, data classes) in one
module and put the code that needs the heavy library in its own module that imports it at the top.

## 3. Modal code (`modal_app/`)

Modal runs your file locally at deploy time (to read the decorators) and again inside the container. The
GPU libraries exist only in the container image, so:

- `music_flamingo.py` is the entry point and does **image, GPU, scaling and lifecycle only**.
- Application code lives in the `flamingo/` package and imports its libraries at the top of each file
  (`vllm_engine.py` imports `vllm`, `hf_engine.py` imports `torch`). The HTTP layer (`api.py`) and shared
  helpers (`common.py`) depend only on light packages, so the tests run on a laptop with no GPU.
- Image-only packages are imported once, right after the image definition, inside `with image.imports():`.
  Modal runs the block in the container and, locally, records the `ImportError` instead of raising. That
  block is the one sanctioned exception to "imports at the top of the file".
- Heavy one-time setup (loading weights, starting the engine) goes in an `@modal.enter()` method, not in
  request handlers and not at import time.
- Pin everything that can change under us: the model revision (a commit hash, never `main`), the locked
  dependency versions (`uv.lock`), and the base image tag.

## 4. Structure

- **Thin entry points, logic in importable modules.** A web route, CLI command, Modal class or agent tool
  validates input, calls a function, and returns. The function does the work and can be tested alone.
- **Separate layers.** Clients (talk to one external service) / services (business logic) / agents and
  tools / schemas (data shapes) do not reach across each other's responsibilities.
- One module, one job, nameable in a few words. A file you cannot summarise in its docstring needs splitting.
- No dead code, no commented-out code, no copy-pasted blocks. Git remembers.
- No magic numbers: a constant with a name and a comment saying where the value comes from.

## 5. Readability

- **Names** (PEP 8): `snake_case` functions and variables, `CapitalizedWords` classes, `UPPER_CASE`
  constants. Names say what a thing is, not how it is used once. No one-letter names beyond loop indices
  and short comprehensions.
- **Type hints** on every function signature (parameters and return). Use built-in generics
  (`list[str]`, `str | None`).
- **Docstrings** (PEP 257) on every public module, class and function: first line says what it does, the
  rest says what is not obvious (units, side effects, errors raised).
- **Comments explain why**, not what. A comment that repeats the code goes; a comment that records a
  measurement, a bug it works around or a decision stays, with the date or a link when it can go stale.
- Small functions. If you need a comment to separate "phase 1" from "phase 2" in one function, they are
  two functions.
- Line length 100 (Ruff-enforced), formatted with `ruff format`.

## 6. Errors and logging

- Catch specific exceptions, never a bare `except:`. Catch broad `Exception` only at a boundary
  (a request handler, an agent tool) that turns it into a clean error, and log it there.
- Never swallow an error silently. Either handle it meaningfully, or log it with context and re-raise or return an
  explicit error value.
- Use `logging`, not `print`, in application code. Log what happened and the identifiers needed to find it;
  never log secrets, tokens or full user content.
- Validate at the boundary (request bodies, tool arguments, environment) with schemas; trust internal calls.

## 7. Dependencies, config, secrets

- **uv only.** Dependencies live in `pyproject.toml` (use dependency groups for separate environments, such
  as `serve` and `dev`); `uv.lock` is committed and is what the Docker image installs. No `pip`, no
  `requirements.txt`.
- Each deployable part has its own environment inside its own folder (`backend/`, `modal_app/`).
- Config comes from environment variables read in one settings module; defaults are safe; secrets are
  never committed, printed or placed in an image layer.

## 8. Project rules for the agent code

- Every capability the agent uses is a **tool** (the agent decides when to call it) or a **hook** (the
  system runs it at a fixed point). A tool may call helpers; the helpers are not separate agent steps.
- MLflow traces the agent flow automatically (LangChain autolog): LLM calls and tool calls with inputs,
  outputs and latency. Do not hand-write spans around things that are already tools; if you think extra
  instrumentation is needed, ask first.
- Keep the agent's tool descriptions and prompts in their own files, reviewed like code.

## 9. Tests

- Every new behaviour ships with a test in the same change. Tests run without network, GPU or paid
  services; anything that does need them is marked (for Modal: `-m live`) and is skipped by default.
- Test the contract (status codes, response shape, auth, failures), not the implementation.
- Fake only at the boundary (a fake engine, a mock HTTP transport); never mock the code under test.
- Run before committing: `uv run pytest` and `uvx ruff check . && uvx ruff format --check .` in the folder
  you changed.

## 10. Working agreements

- Do the thing that was asked. Unrequested refactors, extra features and "while I was in there" changes
  are separate requests, so ask first.
- When setup or run steps change, update `SETUP.md` in the same change. Document each feature in `docs/`
  so it can be reviewed in prose.
- Before saying something is done, say how it was verified, and what was not.

## Review checklist (for a pull request)

- [ ] Imports at the top, grouped; any lazy import carries a comment naming its allowed case.
- [ ] Type hints and docstrings on public functions; no dead or commented-out code.
- [ ] No bare `except`, no swallowed errors, no `print`, no secrets in code or logs.
- [ ] Tests added for the new behaviour; `pytest` and `ruff` pass.
- [ ] `uv.lock` updated if dependencies changed; no `requirements.txt` crept in.
- [ ] `SETUP.md` / `docs/` updated if setup or behaviour changed.
