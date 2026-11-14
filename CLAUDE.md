# Orchestra (music-recommendation): rules for AI assistants

- **Read `CODING_STANDARDS.md` before writing or changing code**, and follow it. It rests on
  [PEP 8](https://peps.python.org/pep-0008/) and the other standards it links (PEP 257, PEP 484, Google
  Python Style Guide, Ruff, Modal docs).
- **Imports go at the top of the file.** Lazy (function-level) imports are allowed only for the cases listed
  in `CODING_STANDARDS.md` section 2, each with a comment. For Modal image-only packages use
  `with image.imports():`.
- **Do not make code changes the user did not ask for.** If a request is ambiguous, ask once.
- **Everything the agent does is a tool or a hook.** MLflow records tools automatically; do not add manual
  spans.
- **uv only** (no pip, no requirements.txt). Each deployable folder has its own environment.
- **Update `SETUP.md`** when setup or run steps change, and document features in `docs/`.
- Run `uv run pytest` and `uvx ruff check . && uvx ruff format --check .` in the folder you changed before
  saying you are done.
- Paid Modal runs: say what they cost first, and stop the app afterwards (`modal app stop music-flamingo --yes`).
