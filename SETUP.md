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
| `SPOTIFY_CLIENT_ID/SECRET` | optional | Provider (track search **and** user-built playlist evidence, doc 9) is skipped if unset. Playlist call budget is tunable via `PLAYLIST_MAX_SEARCHES/FETCHES/TRACKS`, `SPOTIFY_PLAYLIST_CONCURRENCY`, `PLAYLIST_EDITORIAL_WEIGHT` (defaults fine) |
| `YOUTUBE_API_KEY` | optional | " |
| `LASTFM_API_KEY` | optional | " |
| `COMPOSIO_API_KEY` | optional | Turns on Reddit evidence (`docs/10-reddit-composio.md`). Needs the one-time sign-in in section 4b. `COMPOSIO_USER_ID` default is fine; `COMPOSIO_REDDIT_CONNECTED_ACCOUNT_ID` only if you have several Reddit logins |
| `MUSICBRAINZ_CONTACT` | recommended | Contact email for MusicBrainz's User-Agent policy |
| `MUSIC_FLAMINGO_ENDPOINT_URL/API_KEY` | optional | Unset → no audio captions; recommendations still run. Endpoint is the Modal app in `modal_app/` (deploy steps below); API key = the token in `modal_app/.token`. Default `MUSIC_FLAMINGO_TIMEOUT_SECONDS=600` (a cold start took up to ~180 s); redirects are followed because Modal answers requests longer than ~150 s with a 303 |
| `MLFLOW_TRACKING_URI` | optional | `http://localhost:5000`; empty disables MLflow (DB event log still on) |

MusicBrainz and YouTube Music need no credentials, so there is always at least some retrieval.
How to obtain each key: `design/SETUP.md` §4a (local, gitignored).

### Audio captioning endpoint (Modal, separate from the backend)
Lives in `modal_app/` with its own uv env (details, costs, measurements: `modal_app/README.md`).
```bash
cd modal_app && uv sync
uv run modal token new                                        # once; needs a payment method for GPUs
umask 077; openssl rand -hex 24 > .token                      # gitignored
uv run modal secret create music-flamingo-auth AUTH_TOKEN=$(cat .token) --force
uv run modal run music_flamingo.py::download_weights          # once; fills the weights Volume
uv run modal workspace proxy-tokens create --name music-flamingo-backend --json > .proxy-token.json   # secret shown once; gitignored
uv run modal deploy --tag v0.2.0 music_flamingo.py            # prints the endpoint URL; one app, tagged versions
```
The endpoint uses Modal **proxy auth** (`requires_proxy_auth=True`): requests without the proxy token are rejected by Modal
with a 401 *before* any GPU container starts (measured: 1 s, no container). The in-container bearer token stays as a second layer.
The image is built from `modal_app/Dockerfile` and `uv.lock` (vLLM engine by default; `MF_ENGINE=hf` deploys the
plain-transformers baseline). Cold start is about 1-2 minutes; the first call after idle waits for it.
Code layout: `music_flamingo.py` (Modal wiring) + the `flamingo/` package. Local checks, no GPU needed:
`uv run pytest` and `uvx ruff check . && uvx ruff format --check .`. Live contract test against the deployed
endpoint (costs GPU seconds): `MUSIC_FLAMINGO_ENDPOINT_URL=... MUSIC_FLAMINGO_API_KEY=... uv run pytest -m live`.
Put the URL in `MUSIC_FLAMINGO_ENDPOINT_URL`, the bearer token in `MUSIC_FLAMINGO_API_KEY`, and the proxy token's
`Modal-Key` / `Modal-Secret` (from `.proxy-token.json`) in `MUSIC_FLAMINGO_PROXY_KEY` / `MUSIC_FLAMINGO_PROXY_SECRET`; restart the backend.
Live tests and the benchmark read the same variables (the bench also reads `.proxy-token.json`).
**Cost:** Modal bills per second of container uptime (cold start + requests + idle window), nothing when zero containers run.
The idle window is 120 s, so you can leave the app deployed: it scales to zero by itself (check with
`uv run modal app list --json`, field `tasks`). Use `uv run modal app stop music-flamingo --yes` only for a crash-loop
or to retire the app (a stop plus redeploy creates a new App ID, which clutters the usage page). Set a monthly spend limit
in the Modal dashboard (Settings → Billing & limits).

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

### 4b. Reddit through Composio (one-time)
No Reddit developer app is needed; Composio runs the OAuth app and you sign in with a normal Reddit account.
1. Sign up at composio.dev (Hobby plan is free, no card) and copy an API key from the dashboard into `COMPOSIO_API_KEY`.
2. `cd backend && uv run python scripts/composio_reddit_check.py` — prints a link; open it, sign in to Reddit, approve.
   The script then runs a real search + thread read. Add `--schema` to print the tools' parameters.
3. Restart the backend. Reddit tools appear to the retrieval agent whenever `COMPOSIO_API_KEY` is set.
Use an account in good standing. If a call fails, `Tool error (search_reddit_tool): ...` shows in the run trace.

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
More: [docs/07-observability.md](docs/07-observability.md).

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Connect call failed ... 6379` | Redis container stopped → `docker compose up -d redis` |
| Backend can't reach DB | Postgres not up, or you expect port 5432 — it is **5433** |
| MLflow container restarts | Check `docker logs orchestra-mlflow`; the `mlflow` database must exist |
| No MLflow traces appear | `MLFLOW_TRACKING_URI` unset in `.env`, or backend not restarted after setting it |
| Login link never shows | `ENVIRONMENT=test` shows a button on the page; in `development` it's only in the **backend** terminal, never an inbox. Restart the backend after changing `.env` |
| Every song says audio "captioning failed" | Expected without `MUSIC_FLAMINGO_ENDPOINT_URL`, or if the Modal app was stopped (redeploy). `401` → token mismatch with the Modal secret. First call after idle takes ~50 s (cold start); run still works without it |
| Modal: "Please add a payment method to use L40S GPU functions" | Add billing at modal.com/settings |
| `429` on discover | Rate limit — see section 4 for clearing |
| `Redis not reachable at startup` warning | Start Redis; rate limiting and login need it |
| Containers gone after a reboot | They now have `restart: unless-stopped`; if created earlier, `docker compose up -d` once more |
| Spotify export: `409` / "Reconnect" | Token revoked/expired, or account not on the app's allowlist (see section 4) |
| Spotify: `INVALID_CLIENT: Invalid redirect URI` | Dashboard URI doesn't exactly match `http://127.0.0.1:8000/api/spotify/callback` |
| Frontend 401 loop | Token expired → sign in again (tokens issued before the session-id change also lack a session) |

## Changelog
- 2026-11-09 — Modal endpoint now requires a Modal proxy token (`MUSIC_FLAMINGO_PROXY_KEY` / `_SECRET` in `backend/.env`; create it with `modal workspace proxy-tokens create`). Deploys are tagged (`--tag`) and the app is no longer stopped between tests. Captions have no word or token limit.
- 2026-11-09 — Modal idle window (`scaledown_window`) default cut from 600 s to 120 s to reduce idle GPU billing; takes effect on the next `modal deploy`.
- 2026-11-09 — Modal app restructured: engines/API moved into the `flamingo/` package; image-only imports now use `with image.imports():` (no function-level imports). Same deploy commands. Added `CODING_STANDARDS.md` and a repo-root `CLAUDE.md` pointing to it; `modal_app/pyproject.toml` gained the same Ruff config as the backend.
- 2026-11-09 — Caption client: `MUSIC_FLAMINGO_TIMEOUT_SECONDS` default raised from 90 to 600 and redirects are followed (Modal answers requests over ~150 s with a 303). Removed the manual MLflow spans around the YouTube download and caption call; each step now logs its duration instead (`audio download ok`, `music_flamingo call`, `audio analysis done`). Modal `MF_MAX_NEW_TOKENS` now defaults to a 10,000-token safety ceiling (needs a redeploy to take effect).
- 2026-11-02 — Music Flamingo endpoint on Modal (`modal_app/`): deploy/stop steps, token, env values, troubleshooting. Backend code unchanged.
- 2026-10-31 — Frontend redesigned as a chat app; added `npm test` (Vitest). No run-step changes.
- 2026-10-31 — `ENVIRONMENT=test` shows the sign-in link on the login page (no SMTP).
- 2026-10-31 — Spotify playlist export: dashboard redirect URI, Premium/allowlist notes, restart policy.
- 2026-10-29 — Created. Added MLflow service, `MLFLOW_TRACKING_URI`, frontend section.
- 2026-11-01 — Reddit shelved (no `REDDIT_*` vars needed; see `backend/archive/reddit/README.md`). Playlist evidence added: reuses the existing Spotify id/secret, nothing new to run.
- 2026-11-07 — Reddit re-enabled through Composio (section 4b): `uv sync` picks up the new `composio` dependency; `COMPOSIO_API_KEY` + one sign-in.
- 2026-11-08 — Model calls no longer have a read timeout (`OLLAMA_REQUEST_TIMEOUT_SECONDS` now defaults to unset; only connecting is bounded, `OLLAMA_CONNECT_TIMEOUT_SECONDS=15`). Set it to a number to re-enable a silence limit.
- 2026-11-08 — Retrieval budget raised: `RETRIEVAL_MAX_TOOL_CALLS=60`, `RETRIEVAL_MAX_MODEL_ROUNDS=20`; Reddit allowance `RETRIEVAL_MAX_REDDIT_SEARCHES=6` / `RETRIEVAL_MAX_REDDIT_THREADS=4` (now enforced in code and stated in the retrieval prompt).
- 2026-11-08 — Supervisor prompt split: general behaviour in `backend/app/prompts/orchestrator_system_prompt.md` (with when-to-load rules and examples), recommendation workflow in `backend/app/skills/recommendation/SKILL.md`. No setup change; restart the backend to pick up edits.
- 2026-11-08 — This file moved from docs/SETUP.md to the repo root (it covers every part of the repo). Root README rewritten as a complete ordered quickstart (required steps + optional Reddit/Modal/Spotify/MLflow table); no setup change.
