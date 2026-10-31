# API contract (for the frontend)

Base: `/api` (Vite proxies to `http://localhost:8000`). JSON unless stated. Errors are
`{"detail": "..."}` with the status code. Protected routes need `Authorization: Bearer <JWT>`;
**any 401 means the token is missing/expired → send the user to login.** Live schema: `/docs`.

## Auth
| Call | Body → Response |
|---|---|
| `POST /auth/request-link` | `{email}` → `{message, dev_link?}` — `dev_link` only when backend `ENVIRONMENT=test` (no email is ever sent). Always 200. IP rate-limited (429). |
| `POST /auth/verify` | `{token}` → `{access_token, token_type}`; 401 if invalid/used/expired. Token is single-use; the link is `/verify?token=…` on the frontend. |
| `GET /auth/me` | → `{id, email}` |

JWT lasts 60 minutes, no refresh.

## Chat (the main call)
`POST /chat/stream` — body:
```json
{ "message": "songs like Made in Abyss by Kevin Penkin, but calmer",
  "thread_id": null, "include_live": null, "include_covers": null, "target_count": null }
```
- `message` (1–2000 chars, trimmed; blank → 422): **free text** — song names, Spotify/YouTube/YouTube
  Music track links, a description of the music, a follow-up ("darker", "a different artist"), or a
  question about earlier answers ("why did you pick the second one?"). Up to five songs per message.
- `thread_id`: omit to start a new thread; send the `thread_id` from a previous turn to continue it.
  The agent sees the thread's last 6 turns, skips songs already recommended in it, and honours
  "different artist". Threads are stored durably (Postgres, via the interaction log).
- `include_live`, `include_covers`, `target_count` (1–25 per theme): optional defaults; the message
  can override them in words ("live versions please").

Response: `text/event-stream`. Read it with `fetch` (not `EventSource`: it needs POST + auth header).
Frames are `event: <type>\ndata: <json>\n\n`. The backend is an **agent that picks its own tools**,
so there is no fixed list of steps: show what arrives. A turn can also be answered in text only.

```jsonc
{"type":"thread","thread_id":"…","run_id":"…"}                       // always first
// one pair per tool call; call_id links them. Calls can overlap (parallel tools).
{"type":"tool","status":"started","name":"analyze_audio","call_id":"…","args":{"song":"…"}}
{"type":"tool","status":"done|error","name":"…","call_id":"…","duration_ms":1234,"summary":"≤200 chars"}
{"type":"message","text":"…"}                                         // the assistant's reply
{"type":"result","data": <DiscoveryResult>}                           // always last on success
{"type":"error","message":"…","retry_after":1234}                     // failure; retry_after (s) only for rate limits
```
Tool names you may see: `get_session_history`, `resolve_song`, `analyze_audio`,
`retrieve_candidates`, `select_and_diversify`, `write_explanations` (map them to friendly labels;
unknown names must still render). A tool `error` is not fatal — the agent continues. Typical order:
history → resolve → audio → retrieve → select → explain; description-only messages skip audio, and a
question about earlier answers calls only `get_session_history`.

Limits: 60 messages/hour per user; the shared discovery budget (**5 searches/hour per user, 40/day
total**) is charged when a turn first runs audio or retrieval — a text-only answer doesn't spend it.
Exceeding the **message** limit → HTTP 429 *before* streaming starts: body
`{"detail":"Rate limit exceeded, try again later."}` plus a `Retry-After: <seconds>` header (the
same shape as every other 429). Exceeding the **discovery** budget → no HTTP error (the stream has
already started): an `error` SSE event `{"type":"error","message":"Discovery limit reached.","retry_after":<seconds>}`
and the stream ends. Any other failure → `error` event with a generic message and no `retry_after`.
Expect turns that search to take minutes (observed >5 min with the current model). There is no server
time limit by default; the retrieval step is bounded by a tool-call budget instead.

Dev only: `POST /discovery/discover` and `/discovery/discover/stream` run the same agent statelessly
(body `{message, include_live, include_covers, target_count}`; no thread, no history).

## Threads
| Call | Response |
|---|---|
| `GET /threads` | newest first, up to 40: `[{thread_id, title, updated_at, turns}]` — the sidebar. `title` = the thread's first message. Runs from before threads existed appear as one-turn threads. |
| `GET /threads/{id}` | `{thread_id, turns:[{run_id, created_at, message, assistant_text, result\|null, status:"ok"\|"reply"\|"failed", reaction\|null}]}`; 404 if unknown/not yours. `result` is a stored `DiscoveryResult`; `status:"reply"` = text-only answer, `"failed"` = no answer was stored. |

### DiscoveryResult
```jsonc
{
  "run_id": "uuid",                       // needed for feedback / export / history
  "thread_id": "uuid",                    // send back to continue this thread
  "reply": "the agent's message to the user (2–4 sentences)",
  "audio_analysis": [{"query":"", "caption": null|"", "source_url": null|"", "error": null|""}],
  "clusters": [{                          // one per theme; divergent songs → separate clusters
    "theme": "short label",
    "hypothesis": "what kind of songs were searched for",
    "input_songs": ["…"],                 // [] for description-only requests
    "recommendations": [{
      "title": "", "artist": "",
      "sources": ["spotify","reddit"],
      "evidence": [{"source":"", "evidence_type":"", "summary":""}],
      "recommendation_strength": 0.0,      // 0–1, the model's own judgement, not a probability
      "variant": "original|cover|live|remix",
      "explanation": "1–2 human-readable sentences"
    }]
  }]
}
```
`clusters` is empty when nothing was found **or the turn was a text-only answer** — `reply` always
holds the assistant's message; render it as the message. Only a non-empty result has a stored batch
(`run_id` works for feedback/export only then). A cluster can also have no recommendations.
`audio_analysis` may be empty (description-only) and its `error` is expected for every song while
the audio model is not hosted — not a failure.

## Runs, history, export
| Call | Response |
|---|---|
| `GET /runs` | last 20 *batches-or-queries*: `[{run_id, created_at, title, thread_id, reaction\|null}]`. Prefer `/threads` for history; this lists individual runs. |
| `GET /runs/{id}` | a stored `DiscoveryResult` (+`run_id`); 404 if unknown, not yours, or the run failed. |
| `GET /runs/{id}/export?format=csv\|json` | file download (attachment). Needs the auth header → fetch as blob. |

## Feedback
`POST /feedback` `{run_id, reaction, comment?}` → same shape. `reaction`:
`loved_it | pretty_good | mixed | missed`; `comment` ≤ 2000 chars. One row per run; resubmitting
overwrites. 404 for a run that isn't yours. It is stored only — it does not change recommendations.

## Spotify
| Call | Notes |
|---|---|
| `GET /spotify/status` | `{connected:boolean}` |
| `GET /spotify/connect?run_id=<uuid>` | `{url}` → navigate the browser to it (`window.location`). After consent Spotify → backend callback → redirects to `{frontend}/runs/{run_id}?spotify=connected\|denied\|error` (or `/?spotify=…` without a run). |
| `POST /runs/{id}/export/spotify` | body `{name?}` → `{playlist_url, playlist_name, added, not_found:["Title — Artist"]}` |
| `DELETE /spotify/connection` | 204 |

Export errors: `409` not connected / token revoked / account not on the app's allowlist → offer
reconnect · `422` no songs matched on Spotify · `404` unknown run · `502`/`503` Spotify problem or
not configured. Matching is strict, so some songs land in `not_found`.

## Health
`GET /health` → `{app, database, redis}` each `"ok"` or `"unreachable"`.

## Not available (don't build UI that assumes these)
Audio upload · per-track URLs · pagination of `/runs`/`/threads` · deleting or renaming threads ·
the audio model (captions are always empty for now).
