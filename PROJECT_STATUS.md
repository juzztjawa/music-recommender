# Project Orchestra — Implementation Status & Plan

Last updated: 2026-08-09

This is the **implementation** doc — what is actually built, file by file, and what
comes next. It complements `architecture.md` (the *design*: what the system is and
why) and `srs-01.md`–`srs-04.md` (the *requirements*). If you want the reasoning
behind the architecture decisions, read `architecture.md`; this doc tracks the
code that realizes it.

---

## 1. Repository layout (current)

```
music-recommendation/
├── architecture.md              # design doc (v0.1 draft)
├── srs-01.md … srs-04.md        # requirements (frozen v2.0)
├── retrieval-agent-tool-schemas.json  # 6 provider tool schemas (agent-designer skill)
├── PROJECT_STATUS.md            # this file
├── README.md                    # project overview + setup
├── .gitignore
├── docker-compose.yml           # Postgres (5433) + Redis (6379)
├── backend/
│   ├── pyproject.toml           # uv-managed, Python 3.13.9
│   ├── uv.lock                  # locked dependency tree
│   ├── .env.example             # all env vars documented
│   ├── .env                     # local dev config, gitignored
│   ├── .python-version          # pins 3.13.9
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py               # async migrations, targets Base.metadata + settings.database_url
│   │   └── versions/
│   │       └── 0016e7f48c5e_identities_and_sessions.py
│   ├── main.py                  # dev entry point — `uv run main.py` from backend/, see 6.7
│   └── app/
│       ├── __init__.py
│       ├── app.py                # FastAPI app + lifespan + CORS + router mounting (was main.py)
│       ├── config.py            # pydantic-settings, .env-driven
│       ├── db.py                # async SQLAlchemy engine + session factory
│       ├── redis.py             # Redis client
│       ├── models/
│       │   ├── __init__.py
│       │   ├── identity.py      # Identity ORM model
│       │   └── session.py       # Session ORM model
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── auth.py          # RequestLinkRequest, VerifyRequest, TokenResponse
│       ├── services/
│       │   ├── __init__.py
│       │   └── auth.py          # magic-link tokens (Redis), identity/session creation, JWT
│       ├── clients/             # one adapter module per external API (locked decision, §5)
│       │   ├── __init__.py
│       │   ├── email.py         # stub sender — logs the magic link, real provider TBD
│       │   ├── musicbrainz.py   # search_musicbrainz — no auth needed
│       │   ├── youtube_music.py # search_youtube_music (ytmusicapi) — unauthenticated
│       │   ├── spotify.py       # search_spotify — Client Credentials flow (spotipy)
│       │   ├── youtube.py       # search_youtube — YouTube Data API v3 (httpx)
│       │   ├── reddit.py        # search_reddit — read-only app-only auth (praw)
│       │   └── lastfm.py        # search_lastfm — REST (httpx)
│       ├── llm.py               # get_primary_model()/get_fallback_model() — Ollama Cloud (architecture.md §4)
│       ├── agents/
│       │   ├── __init__.py
│       │   └── retrieval.py     # Retrieval & Evidence Agent (langchain.agents.create_agent)
│       └── api/
│           ├── __init__.py
│           ├── deps.py          # get_db, get_redis, get_current_identity
│           └── routes/
│               ├── __init__.py
│               ├── health.py    # GET /api/health
│               ├── auth.py      # POST /auth/request-link, POST /auth/verify, GET /auth/me
│               └── discovery.py # POST /discovery/retrieve — Phase 3 test surface, see §6.4
└── frontend/                     # NOT YET CREATED (Phase 9)
```

---

## 2. Phase 1 — Backend skeleton (DONE, verified, committed `0e9683d`)

### 2.1 What was built, file by file

**`backend/pyproject.toml`** — uv-managed project, `requires-python = ">=3.13"`.
Runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic` + `pydantic-settings` +
`pydantic[email]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `redis`,
`langchain>=1.0`, `langgraph>=1.0`, `langchain-ollama>=1.0`, `python-jose[cryptography]`,
`python-multipart`. Dev deps: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`.
`[tool.uv] package = false` (this is an app, not a distributable package).
Ruff configured: line-length 100, target py313, select E/F/I/W/UP/B.

**`backend/app/config.py`** — `Settings(BaseSettings)` via pydantic-settings, reads
`.env` (extra="ignore"). All settings:
- App: `app_name`, `environment` (development|production), `debug`
- DB: `database_url` default `postgresql+asyncpg://orchestra:orchestra@localhost:5433/orchestra`
- Redis: `redis_url` default `redis://localhost:6379/0`
- LLM: `ollama_base_url` (default localhost:11434), `ollama_api_key` (empty for local),
  `ollama_primary_model` / `ollama_fallback_model` = `deepseek-v4-flash:0731-cloud`
  (originally `kimi-k3:cloud` — see §6.6 for why that changed)
- Auth: `jwt_secret` (default "change-me-in-production" — MUST override), `jwt_algorithm`
  = HS256, `jwt_expire_minutes` = 60, `magic_link_expire_minutes` = 15
- Email: `email_from` (sender TBD — Resend vs SMTP)
- CORS: `cors_origins` default `["http://localhost:5173"]`
Exposes `get_settings()` (lru_cached) and a module-level `settings` singleton.

**`backend/app/db.py`** — `Base(DeclarativeBase)` for all ORM models. Async engine
(`create_async_engine`, `echo=settings.debug`, `pool_pre_ping=True`), `async_sessionmaker`
(`expire_on_commit=False`), and `get_db()` async generator dependency.

**`backend/app/redis.py`** — `redis_client` from `Redis.from_url(settings.redis_url,
decode_responses=True)` and `get_redis()` dependency.

**`backend/app/app.py`** (originally `main.py` — renamed at Phase 3, see 6.7)
— FastAPI app (`title=settings.app_name`, version 0.1.0). `lifespan` pings
Redis on startup (warns, doesn't crash if unreachable) and closes it on
shutdown. CORS middleware from `settings.cors_origins`. Mounts `health.router`
at prefix `/api`. Comment notes feedback/export routers mount as built.

**`backend/app/api/routes/health.py`** — `GET /api/health`. Runs `SELECT 1` against DB
and `ping()` against Redis, returns `{"app","database","redis"}` each "ok" or
"unreachable". Graceful degradation: a down DB/Redis reports "unreachable" rather than
500ing.

**`backend/app/api/deps.py`** — re-exports `get_db`, `get_redis`. Placeholder comment
for `get_current_identity` (implemented in Phase 2).

**`backend/.env.example`** — documents every env var with comments, including the
5433 port note and the local-vs-cloud Ollama distinction.

**`docker-compose.yml`** — `postgres:16-alpine` (user/pass/db `orchestra`, host port
**5433**→container 5432, named volume, pg_isready healthcheck) and `redis:7-alpine`
(host 6379, redis-cli ping healthcheck).

**`backend/Dockerfile`** — `python:3.13-slim`, installs uv, `uv sync --no-dev
--no-install-project`, copies `app/`, runs uvicorn on 0.0.0.0:8000.

**`README.md`** — project overview, architecture summary, repo layout, dev setup
(docker compose, uv sync, uvicorn, npm).

### 2.2 Verification (real, executed)

- `uv sync` installed all deps cleanly on Python 3.13.9.
- Confirmed versions: langchain 1.3.14, langgraph 1.2.10, langchain-ollama 1.1.0,
  fastapi 0.141.1, sqlalchemy 2.0.51, redis 8.1.0, pydantic 2.13.4.
- `docker compose up -d postgres redis` → both healthy.
- Booted uvicorn, hit `GET /api/health` → `{"app":"ok","database":"ok","redis":"ok"}`
  HTTP 200.
- Re-ran an in-process ASGI test (`/tmp/hermes-verify-phase1.py`) → same PASS result.

### 2.3 Environment decisions made

- **Python 3.13.9** (pyenv), NOT 3.14. 3.14 is too bleeding-edge for the stack.
- **Docker Postgres on host port 5433**, not 5432 — your system Postgres already owns
  5432. Docker Postgres and system Postgres coexist; system one untouched.
- **Git repo** initialized on `main`, working tree clean after commit `0e9683d`.

---

## 3. Implementation plan (full roadmap)

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Backend skeleton (config, DB, Redis, FastAPI, health) | ✅ DONE |
| 2 | Auth (magic link + JWT + sessions) | ✅ DONE |
| 3 | Client adapters + Retrieval agent (Spotify/YouTube/MusicBrainz → Reddit → ytmusicapi) | ✅ DONE |
| 4 | Consolidation + selection + diversification (pure Python, unit-tested) | ✅ DONE |
| 5 | Audio agent (yt-dlp → Music Flamingo caption) | ⏭ NEXT |
| 6 | Orchestrator graph + explanation | |
| 7 | SSE streaming + interaction logging + rate limiting | |
| 8 | Feedback (collect/store) + export | |
| 9 | React SPA | |
| 10 | Tests + deploy | |

---

## 4. Phase 2 — Auth (DONE, verified)

### 4.1 Email sender decision

Magic-link delivery needs a transactional email service eventually, but real
provider integration (Resend vs SMTP) was deferred: the email sender is a
**stub** (`app/clients/email.py`) that logs the magic link instead of sending
it. It lives in `clients/` because that's the locked-decision home for all
external API interaction (§5) — once wired to Resend/SMTP it's just another
provider adapter, same shape as the future Spotify/YouTube/Reddit clients.
The call site (`services/auth.py`) doesn't change when a real provider is
wired in later — swap the function body only.

### 4.2 Data model (SQLAlchemy ORM + Alembic migration)

Per `architecture.md` §5, built exactly as specced:

```
identities
  id (pk, uuid), email (unique, indexed), created_at, spotify_oauth_token (nullable text)

sessions
  id (pk, uuid), identity_id (fk -> identities.id, indexed), started_at, ended_at (nullable)
```

- `identities` = the verified tester (FR-18). No password stored.
  `spotify_oauth_token` column exists now but is unencrypted/unused — real
  encryption + the OAuth flow itself land in Phase 8 (export).
- `sessions` = durable row so FR-19's interaction log has something to hang off.
  Ephemeral conversational state itself lives in Redis, keyed by session id
  (not built yet — that's the discovery-flow phases).
- Migration `0016e7f48c5e_identities_and_sessions.py`, generated via
  `alembic revision --autogenerate` and applied with `alembic upgrade head`.

### 4.3 Magic-link flow (built, tested live)

1. `POST /api/auth/request-link` — body `{email}`. Generates a `secrets.token_urlsafe(32)`
   token, stores it in Redis (`magic_link:<token>` → email, TTL = `magic_link_expire_minutes`),
   and calls the stub sender. Always returns 200 regardless of whether the
   email is known — avoids enumeration. Identity creation happens at verify
   time, not request time, so this endpoint works identically for first-time
   and returning testers.
2. `POST /api/auth/verify` — body `{token}`. Atomically reads+deletes the Redis
   key (`GETDEL`, so a token is single-use), 401s if missing/expired,
   get-or-creates the `identities` row, creates a `sessions` row, issues a JWT
   (`sub`=identity id, `exp` = `jwt_expire_minutes`), returns `{access_token, token_type}`.
3. `GET /api/auth/me` — Bearer-JWT-protected, returns `{id, email}`. Built as
   the live proof that `get_current_identity` works end-to-end; also just a
   generically useful "who am I" endpoint going forward.

### 4.4 JWT + session handling

- JWT signed with `jwt_secret` (HS256) via `python-jose`, carries `sub`
  (identity id, UUID) + `exp`.
- Session row created in Postgres on every successful verify (durable, for FR-19).
- Ephemeral state (conversation, in-session dedup) in Redis with TTL — not
  built yet, lands with the discovery flow.

### 4.5 `get_current_identity` dependency

`app/api/deps.py` — `HTTPBearer` extracts the `Authorization: Bearer <jwt>`
header, `decode_access_token` verifies signature + expiry and pulls the
identity id, then the identity is loaded from Postgres. 401s on
missing/invalid/expired token or an identity that no longer exists.

### 4.6 Alembic

`alembic init -t async alembic`, then `alembic/env.py` rewired to import
`Base.metadata` from `app.db` (via `app.models`) and set
`sqlalchemy.url` from `app.config.settings.database_url` at runtime — so
migrations always target whatever `DATABASE_URL` the app itself is
configured with, instead of a static URL living separately in `alembic.ini`.

### 4.7 Config additions

- `frontend_base_url` (default `http://localhost:5173`) — added to
  `Settings` and `.env.example`; used to build the `{base}/verify?token=...`
  magic-link URL.
- `backend/.env` created locally (gitignored) from `.env.example`.

### 4.8 Verification (real, executed)

- `docker compose up -d postgres redis` → both healthy.
- `alembic upgrade head` → `identities` + `sessions` tables created.
- Booted uvicorn, full live round-trip:
  - `POST /auth/request-link` → 200, stub sender logged a real magic-link URL.
  - `POST /auth/verify` with that token → 200, valid JWT returned.
  - `GET /auth/me` with the JWT → 200, correct `{id, email}`.
  - `GET /auth/me` with no token → 403 `{"detail":"Not authenticated"}`.
  - Replaying the same magic-link token → 401 (single-use enforced via `GETDEL`).
  - Confirmed `identities` and `sessions` rows landed correctly via `psql`.
- `uv run mypy app` → clean (added `types-python-jose` dev dep to resolve a
  missing-stubs error).
- `uv run ruff check app` → clean except pre-existing/idiomatic findings
  (FastAPI's `Depends(...)` default-argument pattern trips ruff's `B008`
  across the whole codebase, including Phase 1's `health.py`; one pre-existing
  `E501` in `config.py`). Not regressions from Phase 2.

---

## 5. Key locked decisions (from architecture discussion)

| Area | Decision |
|------|----------|
| Stack | FastAPI + LangChain/LangGraph (v1) + SQLAlchemy + Alembic + Postgres + Redis + React (Vite) |
| Agent pattern | Supervisor (Orchestrator) → subagents-as-tools (Retrieval & Evidence, Audio) → deterministic Selection → single-call Explanation |
| Flow | Strictly sequential: audio → caption → hypotheses → retrieval → evidence → selection → explanation. No fan-out |
| Streaming | SSE via `stream_mode=["messages","custom","updates"]` v2. Generic envelope: `agent_message`/`tool_call`/`tool_result`/`step`. FE renders whatever arrives |
| Sessions | Durable Postgres, fresh LLM context per session, viewable history |
| Feedback | Collect + store only in v1 (adaptation deferred to future) |
| Caching | No prompt-cache code. Domain cache (song profiles + evidence in Postgres) is the real build |
| Third-party | `client/` dir for all external API interaction |
| Credentials | Originally: build with mocks + VCR fixtures, wire keys later. Revised at Phase 3: you chose to create the real dev apps immediately, so adapters are wired against live provider APIs from the start. Automated test fixtures (VCR-recorded) are still the plan for Phase 10's test suite. |
| Python | 3.13.9 (pyenv), NOT 3.14 |
| Postgres port | 5433 (Docker), avoids clash with system Postgres on 5432 |
| Email sender | Stub (console-log the magic link) for now; real Resend/SMTP integration deferred |
| Magic-link storage | Redis only (not Postgres) — TTL-bound, single-use via `GETDEL`, no reason to be durable |
| JWT library | `python-jose[cryptography]` (already a Phase 1 dep) |
| LLM factory location | `app/llm.py`, not `app/clients/` — it's the shared reasoning substrate every agent uses, same precedent as `db.py`/`redis.py` being top-level infra rather than "just another external API client" |

---

## 6. Phase 3 — Client adapters + Retrieval & Evidence Agent (DONE, verified live end-to-end)

### 6.1 Provider client adapters (`app/clients/`)

Built in the order architecture.md §9 item 4 recommended (stable providers
first, `ytmusicapi` last as the least stable/unofficial dependency), plus
Last.fm grouped with the stable batch:

| Provider | File | Auth | Library | Live-tested |
|---|---|---|---|---|
| MusicBrainz | `musicbrainz.py` | None (User-Agent only) | `musicbrainzngs` (sync, run via `asyncio.to_thread`) | ✅ yes, live |
| YouTube Music | `youtube_music.py` | None | `ytmusicapi` (sync, threaded) | ✅ yes, live |
| Spotify | `spotify.py` | Client Credentials flow | `spotipy` (sync, threaded) | ⏳ pending your credentials |
| YouTube Data API | `youtube.py` | API key | `httpx` direct REST | ⏳ pending your credentials |
| Reddit | `reddit.py` | App-only (client id/secret, read-only) | `praw` (sync, threaded) | ⏳ pending your credentials |
| Last.fm | `lastfm.py` | API key | `httpx` direct REST | ⏳ pending your credentials |

Every adapter raises a provider-specific `*NotConfigured` exception when its
credentials are absent, rather than silently returning nothing — but in
practice the agent never triggers that path, because `available_tools()`
(see 6.2) filters unconfigured providers out before the LLM ever sees them
as tools. The exception is a safety net, not the primary mechanism.

All sync provider SDKs (`spotipy`, `praw`, `musicbrainzngs`, `ytmusicapi`) run
via `asyncio.to_thread` so they don't block the event loop; Last.fm and
YouTube Data API talk direct REST via `httpx.AsyncClient` since neither has
(or needs) a heavier SDK.

### 6.2 LLM factory (`app/llm.py`)

`get_primary_model()` / `get_fallback_model()` each build a `ChatOllama`
pointed at `settings.ollama_base_url`, with the API key passed as an explicit
`Authorization: Bearer` header via `client_kwargs` (rather than relying on
the `ollama` package's ambient `os.getenv('OLLAMA_API_KEY')` pickup — kept
the dependency explicit through our own config layer).

Originally this was one `get_chat_model()` returning
`primary_model.with_fallbacks([fallback_model])` (LangChain's built-in
fallback composition). Found live in Phase 3 that this breaks
`create_react_agent`'s `response_format` structured-output step, which
requires a plain `BaseChatModel`/`RunnableBinding` and raises `TypeError:
Expected model to be a ChatModel or RunnableBinding ... got
RunnableSequence` against a `RunnableWithFallbacks`. Fixed by exposing the
two models separately and having callers retry the whole agent call against
the fallback on failure, instead of composing fallback into the model
object — see §6.3 and §6.7.

### 6.3 Retrieval & Evidence Agent (`app/agents/retrieval.py`)

Built with **`langchain.agents.create_agent`** — not
`langgraph.prebuilt.create_react_agent`. That was the original implementation
(and where the two live bugs in §6.7 items 1-3 were found and fixed), but
`create_react_agent` is deprecated as of LangGraph v1, confirmed by querying
the LangChain docs MCP directly against our installed versions
(`langgraph==1.2.10`, `langchain==1.3.14`, both v1). Migrated wholesale to
`create_agent` — see §6.8 for what changed and why, including a genuine
improvement this surfaced (structured output generated in the main loop,
not a bolted-on extra LLM call).

- **Tools**: one `@tool`-decorated async wrapper per provider client, args
  typed via `Annotated[..., Field(...)]` to match the constraints in
  `retrieval-agent-tool-schemas.json` (min/max length, result limits) —
  `infer_schema` builds the tool's JSON schema from these annotations
  directly, no separate schema definition to keep in sync.
- **`available_tools()`**: filters to only providers with configured
  credentials (MusicBrainz + YouTube Music always included). This is the
  actual mechanism for "provider without credentials is skipped" — FR-6.1's
  dynamic provider selection absorbs missing-credential handling for free.
- **Structured output** (`RetrievalResult`): `candidates` (each with
  `title`, `artist`, `sources`, `evidence: list[EvidenceItem]` carrying
  `source`/`evidence_type`/`summary` per FR-7.1 provenance,
  `recommendation_strength` 0.0-1.0 per FR-9.1/9.2, `rationale`),
  `providers_queried`, optional `notes`. Requested via
  `response_format=ToolStrategy(RetrievalResult)` — explicit rather than
  passing the raw schema, since `create_agent` would otherwise auto-pick
  `ProviderStrategy` for models it thinks support native structured output
  and `ToolStrategy` for everything else; being explicit avoids depending on
  that heuristic guessing right for this model.
- **System prompt** (now `system_prompt=`, not `prompt=` — renamed in
  `create_agent`) encodes FR-6.2 (retrieval budget is agent-judgment, not
  fixed), FR-6.3 (~50-100 candidates as a target, not a hard rule), FR-8
  (merge cross-provider duplicates before scoring), and FR-9.2 (holistic
  scoring — one strong source can outscore several weak ones, no chasing a
  target count with weak candidates).
- **Tool-call error handling**: explicit `@wrap_tool_call`-decorated
  middleware (`_handle_tool_errors`) catches any exception from a tool call
  and returns a `ToolMessage` describing it instead of letting it crash the
  run. This is required now — confirmed in the LangChain docs that
  `create_agent`'s tool node does *not* auto-catch exceptions the way the
  deprecated `create_react_agent`'s `ToolNode` default did ("exceptions
  propagate unless `handle_tool_errors` is configured"). Without this
  middleware, a single provider hiccup would kill the whole retrieval run.
- **Model fallback**: `run_retrieval()` builds the agent against
  `get_primary_model()`, and on any exception rebuilds and retries once
  against `get_fallback_model()` (logging the primary failure). Still a
  manual retry, not `.with_fallbacks()` — `create_agent`'s `model` parameter
  has the same `str | BaseChatModel` typing that rejected a
  fallback-wrapped runnable under the old implementation, so the same
  constraint applies here. See §6.2.

### 6.4 Discovery test endpoint (`app/api/routes/discovery.py`)

`POST /api/discovery/retrieve` — protected (same `get_current_identity` as
every other route), takes `{hypothesis: string}` and returns a
`RetrievalResult` directly from the agent. Deliberately takes a hand-written
hypothesis instead of a song: Query Understanding/Hypothesis Generation
(Phase 6) and Audio Analysis (Phase 5) — the components that would normally
produce a hypothesis from a real song — don't exist yet. This route is a
scaffold to make the retrieval agent live-testable now; the Orchestrator will
supersede it, not sit on top of it.

### 6.5 Verification status

- All 6 client adapters: `ruff check` and `mypy` clean (added a
  `[[tool.mypy.overrides]]` entry for `spotipy`/`musicbrainzngs`, which ship
  no type stubs).
- **Live-verified against real APIs**: MusicBrainz (`search_musicbrainz`) and
  YouTube Music (`search_youtube_music`) — both need no credentials, called
  directly with a real query ("Bohemian Rhapsody Queen"), got real results back.
- **Graceful-degradation verified**: Spotify, YouTube, Reddit, Last.fm each
  confirmed to raise their `*NotConfigured` exception cleanly when
  credentials are absent, rather than a confusing lower-level error.
- **Ollama Cloud connectivity**: confirmed live — a direct `get_primary_model().ainvoke(...)`
  call against `deepseek-v4-flash:0731-cloud` returned a correct response.
- **Full agent run, end-to-end, confirmed live and working**: hypothesis
  `"upbeat 90s alternative rock with distorted guitars, similar to early
  Weezer"` → 16 real, well-formed candidates (Weezer tracks, lineage matches
  like The Rentals via bassist Matt Sharp, genre-adjacent 90s power-pop),
  each with evidence, provenance, and a 0.0-1.0 strength score, queried live
  against YouTube Music + MusicBrainz. This got through all three bugs in
  §6.6 before succeeding.
- One residual flake observed: on that same run, the *first* extraction
  attempt returned `None` instead of a valid result (see §6.6 item 3) —
  the retry-with-fallback mechanism absorbed it and the retry succeeded
  cleanly, so this didn't surface as a failure, but it's a sign the
  structured-extraction call isn't 100% reliable per-call. Not hardened
  further yet — revisit if it recurs often enough to be annoying.
- **Not yet live-verified**: the four credentialed providers (needs their
  respective keys — Ollama Cloud is now in place, provider keys still
  pending). The app boots cleanly and `/api/discovery/retrieve` is
  registered and reachable (confirmed via `/openapi.json`).
- `SETUP.md` §4b documents exactly how to run this live test. You're now
  driving live testing going forward — this doc gets updated from what you
  report, not from further agent-run test loops here.

### 6.6 Incident: `kimi-k3:cloud` unusable on the current plan, model swapped live

Running the retrieval agent for real (first live end-to-end attempt) surfaced
two problems in sequence, both now fixed:

1. **`kimi-k3:cloud` — HTTP 402.** `"this model uses extra usage only (not
   included plan usage) and your extra usage balance is empty, add extra
   usage or turn on auto reload at https://ollama.com/settings"`. Not a code
   bug — an Ollama Cloud account/plan limitation. Per your call, `kimi-k3:cloud`
   is dropped entirely; `deepseek-v4-flash:0731-cloud` is now both primary and
   fallback (config, `.env`, `.env.example`, `architecture.md` all updated —
   grep for `kimi` if you ever see a stale reference). No second confirmed
   working model yet, so there's currently no real fallback diversity — worth
   picking a distinct second model once you've verified another one works
   under your plan.
2. **`.with_fallbacks()` incompatible with `create_react_agent`'s
   `response_format`.** Once the primary failure above correctly triggered
   the fallback path, the fallback call itself threw `TypeError: Expected
   model to be a ChatModel or RunnableBinding ... got RunnableSequence` —
   `create_react_agent`'s structured-output step does a strict isinstance
   check that a `RunnableWithFallbacks` fails. Fixed by moving fallback out
   of the model object and into a retry at the call site (§6.2/§6.3). This
   is a real constraint of the installed LangGraph version, not something
   specific to Ollama — worth remembering for the Orchestrator and
   Explanation LLM calls in later phases, which will hit the same thing if
   they also use `response_format`.
3. **`deepseek-v4-flash:0731-cloud` doesn't honor `json_schema`-method
   structured output.** After fixing #2, the retry attempt raised
   `OutputParserException: Invalid json output` (empty content) on the
   structured-response step. Isolated with a minimal repro outside the full
   agent: asked `model.with_structured_output(Simple)` (a one-field schema)
   "What is 2+2?" — expected `{"answer": "4"}`, got the model just answering
   `4` as if the structured-output instruction wasn't applied at all.
   `create_react_agent`'s `response_format` always calls
   `.with_structured_output(schema)` with no way to pass `method=`, and its
   default is `method='json_schema'` — which this model doesn't reliably
   respect. Confirmed `method='function_calling'` works correctly (matches
   architecture.md's existing premise that Ollama Cloud models are
   tool-calling capable — that strength carries over to structured output
   requested via tool-calling, just not via native JSON-schema constrained
   decoding). Fixed by **not** using `create_react_agent`'s `response_format`
   at all: `_build_agent()` now runs the ReAct tool-calling loop with no
   `response_format`, and a separate `_extract_result()` does one explicit
   `model.with_structured_output(RetrievalResult, method="function_calling")`
   call afterward, against the full message history. Also had to relax the
   return-type handling here — `.with_structured_output()` returned a plain
   `dict` in one observed case rather than a `RetrievalResult` instance, so
   `_extract_result` now accepts either and calls `.model_validate()` if it's
   a dict, instead of asserting a specific type.

Confirmed working end-to-end after all three fixes — see §6.5 for the real
successful run. All fixes are in `app/llm.py` and `app/agents/retrieval.py`;
`ruff`/`mypy` clean.

### 6.7 Entry-point fix: `app/main.py` → `backend/main.py` + `app/app.py`

Found live: running `uv run app/main.py` (executing the file directly,
from inside the package it lives in) threw `ModuleNotFoundError: No module
named 'app'`. Root cause, not a code bug: running a `.py` file directly only
puts *that file's own directory* on `sys.path`, not its parent — so from
inside `app/`, the `app` package containing `main.py` was invisible to its
own internal imports (`from app.api.routes import ...`).

Fixed by relocating, not by adding defensive code: the FastAPI app object
moved to `app/app.py` (unchanged otherwise), and a new `backend/main.py` is
the actual entry point — sits one level up, outside the `app` package, so it
can safely `import app.app` and hand it to `uvicorn.run(..., reload=settings.debug)`.
Running it from the wrong place (`cd app && uv run main.py`, or
`uv run app/app.py`) now fails the same way as before if attempted — but the
correct invocation (`uv run main.py` from `backend/`) is the one shown
everywhere (`SETUP.md`, `README.md`, this file), so there's no path that
looks obviously right and silently breaks anymore. Docker's `CMD` still
launches via `uv run uvicorn app.app:app` directly (no reload, no dependency
on the dev entry point) — production and local dev intentionally use
different launch mechanisms.

### 6.8 Migration: `langgraph.prebuilt.create_react_agent` → `langchain.agents.create_agent`

You asked me to check the retrieval agent against current LangChain docs
(via the LangChain docs MCP) rather than assume the implementation was
current. It wasn't: `create_react_agent` is deprecated as of LangGraph v1,
in favor of `langchain.agents.create_agent` — confirmed directly against our
installed versions (`langgraph==1.2.10`, `langchain==1.3.14`), not just
against docs in the abstract. Migrated `app/agents/retrieval.py` fully. What
changed and why:

1. **Import/factory**: `from langgraph.prebuilt import create_react_agent`
   → `from langchain.agents import create_agent`. `prompt=` renamed to
   `system_prompt=`.
2. **Structured output got better, not just renamed.** The old
   implementation (§6.6 item 3) had to work around `create_react_agent`
   hardcoding `method='json_schema'` with no override — fixed then by
   splitting into an unstructured tool-calling loop plus a manual second
   `model.with_structured_output(..., method="function_calling")` call.
   `create_agent` doesn't have that limitation: `response_format=
   ToolStrategy(RetrievalResult)` requests tool-calling-based structured
   output directly, generated **in the main loop** rather than as a bolted-on
   extra LLM call — cheaper (one fewer full LLM round-trip per run) and
   plausibly why the "occasional `None` extraction" flake from §6.5 existed
   at all (a whole separate un-integrated call has more surface for that
   than one built into the loop). Removed the old `_extract_result`/
   `_run_once` two-call plumbing entirely — `run_retrieval` is back to one
   `agent.ainvoke(...)` per attempt, reading `result["structured_response"]`
   directly, same key as before.
3. **Tool error handling is no longer implicit.** The old `create_react_agent`
   used `ToolNode`, whose default already converted a tool exception into an
   error message instead of crashing — I noted this in §6.3 originally and
   built nothing extra because of it. `create_agent`'s docs state plainly:
   "exceptions propagate unless `handle_tool_errors` is configured" — no
   longer a safe default. Added an explicit `@wrap_tool_call`-decorated
   `_handle_tool_errors` middleware to restore the same resilience (a single
   provider failing mid-run doesn't kill the whole retrieval). This is a
   real behavior change in the framework, not a config toggle I'd have found
   by guessing — worth remembering for the Orchestrator and Explanation
   agents in later phases, which will need the same middleware if they use
   `create_agent` with tools.
4. **`.with_fallbacks()` constraint carries over.** `create_agent`'s `model`
   parameter is still typed `str | BaseChatModel`, same as
   `create_react_agent`'s internal check that rejected a
   `RunnableWithFallbacks` (§6.6 item 2) — so the manual
   try-primary-except-rebuild-with-fallback pattern in `run_retrieval` is
   unchanged, not something this migration could remove.

Verified: `available_tools()` still correctly reports `['search_musicbrainz_tool',
'search_youtube_music_tool']` with no provider credentials configured, and
`_build_agent()` compiles to a `CompiledStateGraph` with no errors — a
structural check with no LLM calls (no cost), stopping short of a full live
run since you're now driving live testing (see §6.5). `ruff`/`mypy` clean
across the whole app after the migration.

---

## 7. Phase 4 — Consolidation, Selection & Diversification (DONE, verified)

Pure, deterministic Python per architecture.md §2 — no LLM call, no new
external credentials. Implements FR-8 (consolidation), FR-9.2 (no padding to
hit a count), FR-10.1-10.5 (diversification), FR-11 (final batch size).

### 7.1 `Candidate` gained a `variant` field (`app/agents/retrieval.py`)

FR-10.3/10.4/10.5 need to distinguish original/cover/live/remix, and nothing
in the Phase 3 schema carried that signal. Rather than add a second pass that
re-reads all the evidence just to classify it, the Retrieval & Evidence Agent
now classifies `variant: Literal["original", "cover", "live", "remix"] =
"original"` itself, in the same structured-output call — it already reads
exactly this kind of metadata (MusicBrainz release type, title conventions,
discussion). One field added to `Candidate`, one instruction added to
`SYSTEM_PROMPT`. Nothing else in the Phase 3 agent changed.

### 7.2 `app/services/selection.py` (new)

Pure functions over `list[Candidate]`, no DB/Redis/async:

- `merge_duplicates` — groups by normalized `(artist, title)`. This is an
  exact-match safety net, not the primary dedup mechanism — the agent already
  merges duplicates it recognizes semantically during retrieval (its system
  prompt says so from Phase 3). A merged candidate keeps the union of
  `sources` and `evidence` (FR-8) and takes `recommendation_strength`/
  `rationale`/`variant` from whichever original member scored highest —
  finding the same song via more providers is corroborating evidence, not a
  reason to average the score down.
- `filter_variants` — drops `variant == "live"` unless `include_live` is set
  (FR-10.4). Drops `variant == "cover"` only when an `"original"` of the same
  normalized *title* is also present in the pool (FR-10.3) — a cover with no
  original present is kept rather than lost. Both are opt-in overrides, since
  there's no Query Understanding step yet (Phase 6) to infer "user explicitly
  asked for the live version" from conversation.
- Sorting applies a `0.85` multiplier to `recommendation_strength` for
  `variant == "remix"` (FR-10.5: remixes are eligible, just generally lower
  priority) — a documented, tunable constant, not exclusion.
- `apply_artist_diversity` — caps at `max_per_artist` (default 3, FR-10.1),
  walking the already-sorted list so the highest-scored song per artist
  survives the cap.
- `select_recommendations` — the full pipeline: merge → filter → rank →
  diversify → trim to `target_count` (default 10, FR-11). Trims, never pads:
  if fewer candidates survive filtering than `target_count`, it returns fewer
  (FR-9.2 — never recommend weak candidates just to hit a requested count).

### 7.3 Wiring (`app/schemas/discovery.py`, `app/api/routes/discovery.py`)

`RetrievalRequest` gained `include_live: bool = False`, `include_covers: bool
= False`, `target_count: int = Field(10, ge=1, le=25)`. `POST
/api/discovery/retrieve` now runs `select_recommendations(...)` on the
agent's raw candidates before returning — same `RetrievalResult` response
shape as Phase 3, but `candidates` is now the filtered/ranked/capped/trimmed
batch instead of the raw ~50-100.

### 7.4 Tests (`backend/tests/services/test_selection.py`, new `tests/` tree)

14 plain-sync `pytest` cases (no DB/Redis fixtures needed — pure functions),
covering: FR-8 merge (sources/evidence combined, score = max of group),
FR-10.2 exact-duplicate collapse, FR-10.1 artist cap, FR-10.3 cover
inclusion/exclusion (with and without an original present, with and without
`include_covers`), FR-10.4 live inclusion/exclusion, FR-10.5 remix
deprioritization, FR-11/FR-9.2 trim-not-pad behavior, and one full-pipeline
integration case exercising all five stages together.

### 7.5 Verification (real, executed)

- `uv run pytest tests/` → 14 passed.
- `uv run ruff check app tests` → clean.
- `uv run mypy app` → clean, no new overrides needed.
- Booted the app in-process (`TestClient`) and confirmed via `/openapi.json`
  that `/api/discovery/retrieve` is still registered and its request schema
  now includes `include_live`/`include_covers`/`target_count`.
- Not yet re-run against a live hypothesis end-to-end (that needs Ollama Cloud
  + provider credentials, same as Phase 3) — the pipeline itself is fully
  unit-tested; a live sanity pass is the next thing to do manually per
  SETUP.md §4c before moving on to Phase 5.

### 7.6 Incident: `_handle_tool_errors` was sync, agent runs async — `NotImplementedError`

Live-testing `/api/discovery/retrieve` for the first time since the Phase
3→4 migration (full auth round-trip, then a real hypothesis) surfaced a bug
in the Phase 3 agent that unit tests couldn't catch: any tool call at all
crashed the run with

```
NotImplementedError: Asynchronous implementation of awrap_tool_call is not
available. You are likely encountering this error because you defined only
the sync version (wrap_tool_call) and invoked your agent in an asynchronous
context (e.g., using `astream()` or `ainvoke()`).
```

Root cause: `_handle_tool_errors` in `app/agents/retrieval.py` was a plain
`def` decorated with `@wrap_tool_call`, but `run_retrieval` calls
`agent.ainvoke(...)`. LangGraph's `ToolNode` does not auto-adapt a sync
`wrap_tool_call` to an async run — it requires an async implementation
(`awrap_tool_call`) when the agent is invoked asynchronously, and raises
immediately on the first tool call otherwise. This applied to every tool
call, not just failing ones, so it was never a "silent until something goes
wrong" bug — it should have failed the very first live agent run. Best guess
is Phase 3's original live verification (§6.5) either predates this
middleware being added or ran under slightly different conditions; not
fully reconstructable from git history since Phases 2-4 were only committed
together as of this session. Either way, this is now fixed and confirmed
live, not theoretical.

Fix: made `_handle_tool_errors` an `async def`, matching the exact fix the
error message itself recommends ("use the `@wrap_tool_call` decorator on a
standalone async function"), and `await handler(request)` instead of calling
it directly. One-line-equivalent change, `app/agents/retrieval.py` only.

**Verified live end-to-end after the fix**: `POST /api/discovery/retrieve`
with hypothesis "upbeat 90s alternative rock with distorted guitars, similar
to early Weezer", `include_live=false`, `include_covers=false`,
`target_count=10` → HTTP 200 in ~89s. Response: exactly 10 candidates
(Superdrag, The Rentals, Nerf Herder, Fountains of Wayne, Material Issue,
Sloan, Jellyfish, Teenage Fanclub, The Posies, Sugar), strictly sorted by
`recommendation_strength` descending (0.92 → 0.70), all `variant: "original"`
(no live/cover leaked through the default filters), one song per artist
(well under the 3-per-artist cap), and every candidate carries
`sources: ["youtube_music", "musicbrainz"]` — confirming FR-8 consolidation
is actually merging cross-provider duplicates in a real run, not just in
unit tests. `providers_queried` correctly reflected only the two
credential-free providers configured in this environment.
`uv run pytest tests/`, `ruff`, `mypy` all still clean after the fix.

---