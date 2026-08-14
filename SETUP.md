# Project Orchestra — Local Setup

What you need on your machine to run and test the backend as it exists right
now (Phase 1-3: skeleton, auth, retrieval agent). This file grows with each
phase — every phase gets its own "how to test it" section below.

---

## 1. Prerequisites

Confirmed already on this machine:

| Tool | Required version | Check |
|---|---|---|
| Python | 3.13.9 via `pyenv` | `pyenv versions` — should show `3.13.9`, pinned by `backend/.python-version` |
| `uv` | any recent | `uv --version` |
| Docker + Compose | any recent | `docker compose version` |

Also needed as of Phase 3: an Ollama Cloud API key (the retrieval agent needs
an LLM to reason), and optionally Spotify/YouTube/Reddit/Last.fm credentials
— see §4a. No Node/frontend needed yet (that's Phase 9).

---

## 2. One-time setup

```bash
cd backend

# Install dependencies into a local .venv (uv creates/manages it)
uv sync

# Copy env template and fill in real values
cp .env.example .env
```

Open `backend/.env` and check:
- `DATABASE_URL` / `REDIS_URL` — defaults match `docker-compose.yml`, no changes needed for local dev.
- `JWT_SECRET` — the default (`change-me-in-production`) is fine for local dev.
  **The app will refuse to start if `ENVIRONMENT=production` and this is still
  the default** — that's intentional, not a bug, if you ever deploy this.
- `EMAIL_FROM` / email delivery — currently a **stub**: magic links are printed
  to the server console/log instead of actually emailed. No email provider
  account needed yet.

---

## 3. Every time you want to run it

```bash
# 1. Start Postgres (5433) + Redis (6379)
cd /home/jawahar/jawahar/Projects/music-recommendation
docker compose up -d postgres redis

# 2. Apply any pending migrations
cd backend
uv run alembic upgrade head

# 3. Run the API
uv run main.py
```

This runs from `backend/main.py` (not `app/main.py` — the entry point
deliberately lives outside the `app` package; see the docstring in
`backend/main.py` if you're curious why). Always run it from the `backend/`
directory — `uv run app/app.py` or `cd app && uv run main.py` will both fail
with `ModuleNotFoundError: No module named 'app'`, because Python only adds a
directly-run script's own folder to its import path, not the parent
directory that actually contains the `app` package.

Leave Postgres/Redis running between sessions if you like — `docker compose up -d`
is idempotent and won't recreate anything that's already up. Stop them with
`docker compose down` (data persists in the named volume; add `-v` only if you
want to wipe the DB).

---

## 4. How to actually test it right now

There's **no frontend yet** (that's Phase 9) — so "testing" today means
exercising the API directly. Three ways, easiest first:

### Option A — Swagger UI (recommended)

With the server running, open **http://localhost:8000/docs** in a browser.
Every endpoint is listed with a "Try it out" button — fill in the body, hit
Execute, see the real response. This is the fastest way to poke at the auth
flow without writing any commands.

### Option B — curl

```bash
# 1. Request a magic link
curl -s -X POST http://localhost:8000/api/auth/request-link \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'

# 2. The "email" is stubbed — find the link in the uvicorn terminal output,
#    it looks like:
#    [stub email] Magic link for you@example.com: http://localhost:5173/verify?token=...
#    Copy the token value.

# 3. Verify it to get a JWT
curl -s -X POST http://localhost:8000/api/auth/verify \
  -H "Content-Type: application/json" \
  -d '{"token":"PASTE_TOKEN_HERE"}'
# -> {"access_token": "...", "token_type": "bearer"}

# 4. Use the JWT to call a protected route
curl -s http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer PASTE_ACCESS_TOKEN_HERE"
```

### Option C — health check only

```bash
curl -s http://localhost:8000/api/health
# -> {"app":"ok","database":"ok","redis":"ok"}
```

### What you still can't test

The full product flow — "give me a song, get a ranked/explained batch of
recommendations back" — needs Phases 5-6 (audio understanding, the
Orchestrator's query understanding + hypothesis generation) before it's a
single request. And there's no UI until Phase 9. But as of Phase 3 (below),
you *can* test the actual retrieval/evidence-gathering machinery — just by
supplying a hypothesis directly instead of a song.

---

## 4b. Testing Phase 3 — the Retrieval & Evidence Agent

This is the first phase with real, LLM-driven feature behavior to test, not
just infrastructure. `POST /api/discovery/retrieve` runs the actual
Retrieval & Evidence Agent: it decides which providers to query, calls them,
gathers evidence, and scores candidates — for real, live, against whichever
providers you've configured credentials for. **Confirmed working end-to-end**
with a real hypothesis against MusicBrainz + YouTube Music (16 well-formed,
correctly-scored candidates) — see `PROJECT_STATUS.md` §6.5/§6.7 if you hit
an error and want to check whether it's a known issue already diagnosed
there before assuming it's new.

**Prerequisite:** `OLLAMA_BASE_URL` + `OLLAMA_API_KEY` must be set in
`backend/.env` (see §4a above) — every call to this endpoint needs the LLM to
reason about which tools to call and how to score results. Without it, the
request will fail when it tries to reach Ollama.

**Which providers actually respond depends on what's in your `.env`:**
MusicBrainz and YouTube Music always work (no credentials needed); Spotify,
YouTube, Reddit, and Last.fm only get called if their keys are set — the
agent silently skips whatever isn't configured rather than failing, so you
can start testing with zero provider keys (Ollama key only) and watch more
providers light up as you add credentials.

### How to test

1. Get a JWT first (see §4 Option B, steps 1-3 — auth is still required, this
   is a protected route like everything else).
2. Either use **Swagger UI** (`/docs`, click the padlock icon and paste
   `Bearer <your JWT>` to authorize, then try `POST /discovery/retrieve`), or curl:

```bash
curl -s -X POST http://localhost:8000/api/discovery/retrieve \
  -H "Authorization: Bearer PASTE_ACCESS_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"hypothesis": "upbeat 90s alternative rock with distorted guitars, similar to early Weezer"}'
```

Expect a real, non-instant response — the agent makes multiple live tool
calls, then a separate LLM pass to extract the final structured result, so
**one to a few minutes is normal**, not a hang. Shaped like:

```json
{
  "candidates": [
    {
      "title": "...", "artist": "...",
      "sources": ["musicbrainz", "youtube_music"],
      "evidence": [{"source": "...", "evidence_type": "...", "summary": "..."}],
      "recommendation_strength": 0.0,
      "rationale": "..."
    }
  ],
  "providers_queried": ["musicbrainz", "youtube_music"],
  "notes": null
}
```

Try a few different hypotheses (specific artist/genre/mood descriptions work
better than vague ones) and watch `providers_queried` grow as you add more
provider credentials to `.env` — no restart needed for env changes to take
effect on `uvicorn --reload`, but you do need to restart if you're not
running with `--reload`.

The extraction step is occasionally flaky (rare — one observed case where it
had to self-recover via the built-in retry). If a request ever fails outright
rather than just being slow, just retry it once before assuming something's
broken.

### What this endpoint deliberately is *not*

It takes a hand-written hypothesis string, not a song — that's intentional.
Turning an actual input song into a hypothesis is Query Understanding +
Hypothesis Generation (Phase 6) and Audio Analysis (Phase 5), neither of
which exist yet. This route exists so the retrieval machinery itself is
testable now instead of waiting for the whole pipeline. It'll be superseded,
not built on top of, once the Orchestrator lands.

---

## 4c. Testing Phase 4 — Consolidation, Selection & Diversification

This phase is pure Python (no LLM call, no new credentials) — most of it is
tested with fast unit tests, no server needed:

```bash
cd backend
uv run pytest tests/ -v
```

`/api/discovery/retrieve` (same endpoint as §4b) now returns the *final*
batch instead of the raw ~50-100 scored candidates: duplicates across
providers merged, live recordings and redundant covers dropped, remixes
ranked lower, capped at 3 songs per artist, trimmed to (by default) 10. The
request body has three new optional fields:

```bash
curl -s -X POST http://localhost:8000/api/discovery/retrieve \
  -H "Authorization: Bearer PASTE_ACCESS_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "hypothesis": "upbeat 90s alternative rock with distorted guitars, similar to early Weezer",
    "include_live": false,
    "include_covers": false,
    "target_count": 10
  }'
```

`include_live` / `include_covers` default to `false` (FR-10.3/10.4 — excluded
unless explicitly requested); `target_count` defaults to 10 (FR-11) and
accepts 1-25. If fewer candidates survive filtering than `target_count`,
you'll get fewer back — that's intentional (FR-9.2: never pad with
weakly-supported candidates just to hit a count).

---

## 4a. Getting API credentials (do this now, in parallel with Phase 3 build)

Six providers total. **MusicBrainz needs no account** (just a descriptive
User-Agent string, not a secret) and **YouTube Music search works
unauthenticated** via `ytmusicapi`. That leaves four you actually need to go
get:

### Ollama Cloud
Confirmed working setup — put your key in `backend/.env`:
```
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=your-key-here
OLLAMA_PRIMARY_MODEL=deepseek-v4-flash:0731-cloud
OLLAMA_FALLBACK_MODEL=deepseek-v4-flash:0731-cloud
```
(`https://ollama.com` is correct, not `https://ollama.com/api` — the client
library appends `/api/...` itself.) `kimi-k3:cloud` was tried first and
dropped: it returns HTTP 402 ("this model uses extra usage only... your
extra usage balance is empty") under this account's current plan. If you add
usage credit or a second confirmed-working model later, swap
`OLLAMA_FALLBACK_MODEL` to something different from the primary — right now
they're intentionally the same model since there's no second one confirmed
to work yet.

### Spotify
1. Go to https://developer.spotify.com/dashboard and log in with any Spotify account (free tier is fine).
2. Click **Create app**. Name/description can be anything. For **Redirect URI**, enter `http://localhost:5173/callback` — it's required by the form but unused until Phase 8 (playlist export needs a real user login; search doesn't).
3. Save, open the app, click **Settings** → copy the **Client ID** and **Client Secret**.
4. This gets you the Client Credentials flow (app-only auth, no user login) — enough for catalog search. The Authorization Code flow for playlist export is a separate, later step (Phase 8).

### YouTube Data API
1. Go to https://console.cloud.google.com/ and create a project (or reuse one).
2. **APIs & Services → Library** → search "YouTube Data API v3" → **Enable**.
3. **APIs & Services → Credentials** → **Create Credentials → API key**.
4. Optional but recommended: click the new key → restrict it to "YouTube Data API v3" only.
5. Free quota is 10,000 units/day; a search call costs 100 units (~100 searches/day) — fine for a bounded tester cohort.

### Reddit
1. Log into Reddit, go to https://www.reddit.com/prefs/apps.
2. Click **create another app...** at the bottom.
3. Type: **script**. Name: anything (e.g. "orchestra-recommender"). Redirect URI: `http://localhost:8000/callback` (required field, unused for script-type apps).
4. Create it. The **client ID** is the string under the app name (looks like `Ab12Cd34Ef56`); the **secret** is labeled "secret".
5. Reddit's API requires a descriptive User-Agent — I'll set one like `orchestra-recommender/0.1 by u/<your-reddit-username>` in config; no extra step needed from you beyond telling me your Reddit username, or I'll use a placeholder you can edit in `.env`.

### Last.fm
1. Go to https://www.last.fm/api/account/create and fill in application name/description (no callback URL needed for read-only API-key access).
2. Copy the **API key** it gives you (ignore the "shared secret" — that's only for write operations we don't use).

### MusicBrainz
Nothing to sign up for. I'll set a User-Agent header identifying the app
(name + version + contact, per MusicBrainz's API etiquette) — you can put a
real contact email in `.env` if you want, otherwise a sensible default ships.

### Where these go

Once you have them, add to `backend/.env` (a matching `.env.example` entry
will exist by the time each provider's adapter lands):
```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
YOUTUBE_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=orchestra-recommender/0.1 by u/your-username
LASTFM_API_KEY=
MUSICBRAINZ_CONTACT=you@example.com
```
You don't need all of them before I start — I'm building each adapter to
degrade gracefully (a provider without credentials is simply skipped, which
is consistent with FR-6.1: the system already has to dynamically decide which
providers to query). Drop keys in as you get them; no restart-order
dependency.

---

## 5. Editor setup (fixes the Pylance "import could not be resolved" warnings)

If your editor shows red squiggles on `fastapi`, `sqlalchemy`, etc. even
though `uv run` works fine from the terminal, it's pointed at the wrong Python
interpreter — it needs to use the project's `.venv`, not your system Python or
pyenv's bare 3.13.9.

- **VS Code / Cursor**: `Ctrl+Shift+P` → "Python: Select Interpreter" →
  choose `backend/.venv/bin/python` (or paste that path if it's not listed).
- Confirm: the bottom-left status bar should show a Python version with
  `('.venv': venv)` next to it, not just a bare version number.

---

## 6. Where things stand / what's next

`PROJECT_STATUS.md` at the repo root is the living implementation log — what's
built, file by file, and the roadmap for what's next (currently: Phase 5,
the audio agent). Read that before starting new work; `architecture.md` has
the *why* behind the design if you want the reasoning.
