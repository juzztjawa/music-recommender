# Project Orchestra — evidence-driven music discovery engine

"Rediscover the feeling that made you love a song."

Project Orchestra is a music discovery engine that understands *why* you connected
with a song and uses evidence gathered from multiple independent sources to
recommend music that preserves the same feeling while encouraging meaningful
discovery.

## Architecture

- **Backend:** FastAPI + LangChain/LangGraph + SQLAlchemy + PostgreSQL + Redis
- **Supervisor agent:** a conversational agent that decides per message whether to recommend, break down one song, answer about earlier results, or just talk. The recommendation workflow is a skill (`backend/app/skills/`), the rest is its system prompt
- **Retrieval sub-agent:** Spotify (tracks and user-built playlists), Reddit (through Composio), YouTube, YouTube Music, MusicBrainz, Last.fm → deterministic selection → explanation
- **Frontend:** React SPA (Vite), chat UI
- **LLM:** Ollama Cloud (`glm-5.3-flash:cloud`)
- **Audio understanding:** Music Flamingo 8B on Modal (optional, separate deploy)
- **Tracing:** MLflow

Design: `design/architecture.md` and `design/srs-01.md`–`srs-04.md`. Code walkthrough: `docs/README.md`.

## Repository layout

```
backend/     FastAPI app, agents, prompts, skills, tests
frontend/    React SPA
modal_app/   Music Flamingo audio captioning endpoint (own uv env, deployed separately)
docker/      Postgres init scripts
docs/        Review docs and API contract
design/      Architecture and requirements
```

## Setup

Prerequisites: Docker + Compose, Python 3.13 with [`uv`](https://docs.astral.sh/uv/), Node 20+, `ffmpeg`.
Everything is `uv` (no pip). [`SETUP.md`](SETUP.md) has the details, env table and troubleshooting for each step.

**Required**

1. **Infrastructure and database** (repo root)
   ```bash
   docker compose up -d postgres redis mlflow
   cd backend && uv sync && cp .env.example .env
   uv run alembic upgrade head
   ```
2. **Fill `backend/.env`**: at minimum `OLLAMA_BASE_URL`, `OLLAMA_API_KEY` and `ENVIRONMENT=test` (shows the sign-in link on the login page). Everything below is optional and the app degrades without it.
3. **Run it**
   ```bash
   cd backend && uv run main.py      # http://localhost:8000
   cd frontend && npm install && npm run dev   # http://localhost:5173
   ```

**Optional, each adds evidence or features**

| Step | What it adds | Where |
|---|---|---|
| Spotify client id/secret | Track search and user-built playlist evidence | `.env`, `SETUP.md` §4 |
| YouTube / Last.fm keys | More retrieval providers | `.env` |
| `MLFLOW_TRACKING_URI=http://localhost:5000` | Traces of every run | `.env`, `docs/07-observability.md` |
| Reddit via Composio: `COMPOSIO_API_KEY`, then `cd backend && uv run python scripts/composio_reddit_check.py` and sign in to Reddit once | Listener opinion as evidence | `SETUP.md` §4b, `docs/10-reddit-composio.md` |
| Audio captioning on Modal: `cd modal_app && uv sync`, `modal token new`, create the auth secret, `download_weights`, `modal deploy`, then set `MUSIC_FLAMINGO_ENDPOINT_URL` and `MUSIC_FLAMINGO_API_KEY`. Needs a Modal payment method; **stop the app when not testing** (`uv run modal app stop music-flamingo --yes`) | Audio captions of input songs | `SETUP.md` "Audio captioning endpoint", `modal_app/README.md` |
| Spotify playlist export: add the redirect URI in the Spotify dashboard | Export results to a playlist | `SETUP.md` |

Restart the backend after any `.env` change.

## Checks

```bash
cd backend && uv run pytest -q && uv run ruff check app tests
cd frontend && npm run build
```

## Status

`docs/` explains the code and its design decisions (start at `docs/README.md`); `design/PROJECT_STATUS.md` is the phase-by-phase implementation log.
