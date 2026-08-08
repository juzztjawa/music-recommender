# Project Orchestra — evidence-driven music discovery engine

"Rediscover the feeling that made you love a song."

Project Orchestra is a music discovery engine that understands *why* you connected
with a song and uses evidence gathered from multiple independent sources to
recommend music that preserves the same feeling while encouraging meaningful
discovery.

## Architecture

- **Backend:** FastAPI + LangChain/LangGraph (Supervisor pattern) + SQLAlchemy + PostgreSQL + Redis
- **Frontend:** React SPA (Vite)
- **Agents:** Orchestrator (supervisor) → Retrieval & Evidence (tool-calling) + Audio (isolated) → deterministic Selection → single-call Explanation
- **LLM:** Ollama Cloud (`kimi-k3:cloud`, fallback `deepseek-v4-flash:cloud`)
- **Audio understanding:** Music Flamingo 7B on serverless GPU (Modal / RunPod)

See `architecture.md` and `srs-01.md`–`srs-04.md` for the full design and requirements.

## Repository layout

```
backend/     FastAPI + LangGraph application
frontend/    React SPA
shared/      OpenAPI spec / shared types
```

## Development setup

### Prerequisites

- Python 3.13 (via pyenv)
- `uv` (Python package manager)
- Docker + Docker Compose (for Postgres + Redis)

### 1. Start infrastructure

```bash
docker compose up -d postgres redis
```

### 2. Backend

```bash
cd backend
uv sync
cp .env.example .env   # then fill in real values
uv run uvicorn app.main:app --reload
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

## Status

Phase 1 (backend skeleton) in progress.
