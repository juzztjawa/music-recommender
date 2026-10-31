# 3. API, auth, data & limits

## Endpoints (all under `/api`)

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health` | – | App / DB / Redis status |
| `POST /auth/request-link` | – (IP rate-limited) | Email a one-time sign-in link |
| `POST /auth/verify` | – | Exchange link token for a JWT |
| `GET /auth/me` | JWT | Who am I |
| `POST /chat/stream` | JWT + chat limit (60/h) + discovery budget when it searches | **Main endpoint** — body `{message, thread_id?, options}`, SSE |
| `GET /threads`, `GET /threads/{id}` | JWT | Conversations and their turns |
| `POST /discovery/discover`, `/discover/stream` | JWT + rate limit | Dev only: stateless run of the same agent |
| `POST /discovery/discover` | JWT + rate limit | Same flow, single JSON response |
| `POST /discovery/retrieve`, `/analyze-audio` | JWT + rate limit | Dev test surfaces for single agents; superseded, not removed |
| `POST /feedback` | JWT | Batch feedback |
| `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/export?format=csv\|json` | JWT | History & export |

## Login (FR-18, passwordless)
1. `request-link`: random 32-byte token → Redis (15 min TTL) → email with
   `{frontend}/verify?token=…`. **Always returns 200** whatever the email, so it can't be
   used to discover who has an account.
2. `verify`: token is read-and-deleted atomically (`GETDEL`) → single-use. Creates the
   identity on first login, then issues a 60-minute JWT.
3. In dev the "email" is just logged to the backend console (`clients/email.py`). **A real
   sender is still needed before real testers.**

## Data model
- `identities` — id, email.
- `sessions` — a row per login. **Not yet referenced by anything**; the JWT carries only
  the identity id.
- `interaction_events` — append-only log: `run_id`, `event_type`
  (`query | step | recommendation | error | feedback | export`), JSONB `payload`.
  One table with JSONB so a new event type needs no migration.
- `feedback` — one row per run (unique `run_id`); resubmitting replaces it.

## Interaction log (FR-19)
`services/interaction_log.log_event` writes each event in its own short transaction **as
it happens**, so a run that crashes still leaves a trace. A logging failure is swallowed:
observing must never break the request. This is **write-only for the live system**:
nothing reads the log to change recommendations (requirement: no cross-session
personalisation). The only readers are run history/export (a user's own runs).

**Gap:** the log records stage-level steps and the final batch only — *not* individual
tool calls or LLM calls, which FR-19 asks for. That is Phase 7b (doc 6).

## Rate limiting (`services/rate_limit.py`, `api/deps.py`)
Redis fixed-window counters:
- Discovery: 5/hour per user **and** 40/day globally — one shared budget across all
  discovery routes (they all spend the same YouTube quota and LLM balance).
- Request-link: 5/hour per IP.
Exceeding returns `429` with `Retry-After`; the UI shows the wait.

Trade-offs: fixed windows allow a burst at a window boundary (acceptable for budget caps,
not for abuse defence). The counter increments *before* the run, so a failed run still
costs a slot. Behind a proxy, `request.client.host` would be the proxy's IP — fix before
deploying behind one.

## Review checklist
- Is a 60-min JWT with no refresh OK? (User is bounced to login after an hour.)
- The frontend stores the JWT in `localStorage` — standard for an SPA but readable by any
  XSS. Accepted for an invite-only tool?
- Is 40 global discoveries/day enough for a demo, and is it the right failure mode that
  one heavy user can exhaust it for everyone?
