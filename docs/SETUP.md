# Local setup guide

Living document — **update it in the same change whenever setup changes** (new service,
env var, command). See the changelog at the bottom.

## 1. Prerequisites

| Need | Why | Check |
|---|---|---|
| Docker + Compose | Postgres, Redis, MLflow | `docker compose version` |
| Python 3.13 + [`uv`](https://docs.astral.sh/uv/) | Backend | `uv --version` |
| Node 20+ / npm | Frontend | `node -v` |
| `ffmpeg` | Audio extraction (yt-dlp) | `ffmpeg -version` |

Docker's data should live on a fast disk (the NVMe root here), not under `/home` on the HDD.

## 2. One-time setup

```bash
# Backend deps + env file
cd backend
uv sync
cp .env.example .env        # then edit — see section 4

# Frontend deps
cd ../frontend
npm install
```

Start infrastructure and migrate (from the repo root):

```bash
docker compose up -d postgres redis mlflow
cd backend && uv run alembic upgrade head
```

**Existing Postgres volume only** (created before MLflow was added) — create its database once:
```bash
docker exec orchestra-postgres psql -U orchestra -c "CREATE DATABASE mlflow"
```
A fresh volume does this automatically via `docker/postgres-init/`.

The first MLflow start `pip install`s itself and takes about a minute.

## 3. Every time you run it

Three terminals (or run the first as a background service):

```bash
# 1. Infra (repo root) — skip if already up
docker compose up -d postgres redis mlflow

# 2. Backend  → http://localhost:8000  (docs at /docs)
cd backend && uv run main.py

# 3. Frontend → http://localhost:5173  (proxies /api to :8000)
cd frontend && npm run dev
```

| URL | What |
|---|---|
| http://localhost:5173 | The app |
| http://localhost:8000/docs | Swagger UI for the API |
| http://localhost:5000 | MLflow traces (experiment `orchestra`) |
| http://localhost:8000/api/health | App / DB / Redis status |

### Signing in
There is no email server, so what happens depends on `ENVIRONMENT` in `backend/.env`:

| `ENVIRONMENT` | Sign-in link |
|---|---|
| `test` (what you use locally) | The login page shows an **Open sign-in link** button — click it, no email involved |
| `development` | Hidden from the UI; copy it from the backend terminal: `[stub email] Magic link for …: http://localhost:5173/verify?token=...` |
| `production` | Never exposed (and a real email sender is still to be built; also requires a real `JWT_SECRET`) |

Links are single-use and expire in 15 minutes. JWTs last 60 minutes; after that you are sent back to login.
`test` returns the link in the API response, so anyone who can reach the API could sign in as any email — local use only.

CLI alternative: `cd backend && uv run python scripts/get_dev_token.py you@example.com`
prints a token (backend must be running).

## 4. Configuration (`backend/.env`)

Only the LLM is strictly required; everything else degrades gracefully.

| Variable | Needed? | Notes |
|---|---|---|
| `OLLAMA_BASE_URL`, `OLLAMA_API_KEY` | **Yes** | Ollama Cloud endpoint + key. Without it no LLM stage works. |
| `OLLAMA_PRIMARY_MODEL` / `_FALLBACK_MODEL` | default ok | `glm-5.3-flash:cloud` |
| `DATABASE_URL`, `REDIS_URL` | defaults match compose | Postgres is on host port **5433** |
| `JWT_SECRET` | dev default ok | Must be changed with `ENVIRONMENT=production` (app refuses to start otherwise) |
| `SPOTIFY_CLIENT_ID/SECRET` | optional | Provider is skipped if unset |
| `YOUTUBE_API_KEY` | optional | " |
| `REDDIT_CLIENT_ID/SECRET`, `REDDIT_USER_AGENT` | optional | " |
| `LASTFM_API_KEY` | optional | " |
| `MUSICBRAINZ_CONTACT` | recommended | Contact email for MusicBrainz's User-Agent policy |
| `MUSIC_FLAMINGO_ENDPOINT_URL/API_KEY` | optional | Unset → no audio captions; recommendations still run |
| `MLFLOW_TRACKING_URI` | optional | `http://localhost:5000`; empty disables MLflow (DB event log still on) |

MusicBrainz and YouTube Music need no credentials, so there is always at least some retrieval.
How to obtain each key: `design/SETUP.md` §4a (local, gitignored).

### Spotify playlist export (one-time dashboard step)
Search uses just the client id/secret above. **Exporting a playlist also needs a login with your Spotify account:**
1. https://developer.spotify.com/dashboard → your app → Settings → **Redirect URIs** → add exactly
   `http://127.0.0.1:8000/api/spotify/callback` (Spotify rejects `localhost`; it must be the IP).
   It must match `SPOTIFY_REDIRECT_URI` (that is the default, so nothing to set in `.env`).
2. Dev-mode apps need the **app owner to have Spotify Premium**, and any account that exports must be
   on the app's **User management** allowlist (add your own Spotify email there).
3. In the app: open a result → **Export to Spotify** → approve on Spotify → you are returned to the
   run → press Export again. The playlist is created private.
Tokens are stored encrypted (key derived from `JWT_SECRET` — changing it just means reconnecting).

Rate limits (defaults): 5 discoveries/hour per user, 40/day total. If you hit them while
testing, clear the counters: `docker exec orchestra-redis redis-cli FLUSHDB`
(this also invalidates any pending magic links).

## 5. Checks

```bash
cd backend
uv run pytest -q            # unit tests (no network, no LLM)
uv run ruff check app tests # lint
cd ../frontend
npm run build               # strict type-check + production build
```

## 6. Seeing what a run did

1. Run a discovery in the UI.
2. MLflow → experiment `orchestra` → Traces: tree of stages, LLM calls, tool calls.
3. Or SQL (every event of a run, in order):
   ```bash
   docker exec orchestra-postgres psql -U orchestra -c \
     "select event_type, payload->>'stage' stage, payload->>'tool' tool, payload->>'duration_ms' ms
      from interaction_events order by created_at desc limit 40"
   ```
More: [07-observability.md](07-observability.md).

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Connect call failed ... 6379` | Redis container stopped → `docker compose up -d redis` |
| Backend can't reach DB | Postgres not up, or you expect port 5432 — it is **5433** |
| MLflow container restarts | Check `docker logs orchestra-mlflow`; the `mlflow` database must exist |
| No MLflow traces appear | `MLFLOW_TRACKING_URI` unset in `.env`, or backend not restarted after setting it |
| Login link never shows | `ENVIRONMENT=test` shows a button on the page; in `development` it's only in the **backend** terminal, never an inbox. Restart the backend after changing `.env` |
| Every song says audio "captioning failed" | Expected without `MUSIC_FLAMINGO_ENDPOINT_URL`; run still works |
| `429` on discover | Rate limit — see section 4 for clearing |
| `Redis not reachable at startup` warning | Start Redis; rate limiting and login need it |
| Containers gone after a reboot | They now have `restart: unless-stopped`; if created earlier, `docker compose up -d` once more |
| Spotify export: `409` / "Reconnect" | Token revoked/expired, or account not on the app's allowlist (see section 4) |
| Spotify: `INVALID_CLIENT: Invalid redirect URI` | Dashboard URI doesn't exactly match `http://127.0.0.1:8000/api/spotify/callback` |
| Frontend 401 loop | Token expired → sign in again (tokens issued before the session-id change also lack a session) |

## Changelog
- 2026-10-31 — Frontend redesigned as a chat app; added `npm test` (Vitest). No run-step changes.
- 2026-10-31 — `ENVIRONMENT=test` shows the sign-in link on the login page (no SMTP).
- 2026-10-31 — Spotify playlist export: dashboard redirect URI, Premium/allowlist notes, restart policy.
- 2026-10-29 — Created. Added MLflow service, `MLFLOW_TRACKING_URI`, frontend section.
