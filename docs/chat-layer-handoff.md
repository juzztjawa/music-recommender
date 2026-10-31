# Chat layer — what was done and how to (re)apply it

Written 2026-10-31 for another agent. Some of these changes were later lost/overwritten, so this
describes the **intended design in full**, then **what I observed in the tree afterwards**.
Reconcile against the current code; do not blindly overwrite.

## Goal
Owner hated the UI (one input box per song). Wants a ChatGPT-style app: sidebar history, one
composer at the bottom, live pipeline stages in the thread. The backend only accepted a list of song
titles, so it needed a conversational layer first ("songs like X but a different artist"). Owner chose:
**backend chat layer first, UI after**, and explicitly lifted the "don't edit backend/" rule for it.

## Design (all backend)
1. **Intent step** — `app/agents/chat_intent.py` + `app/prompts/chat_intent_system_prompt.txt`.
   One non-agentic structured LLM call (`app.llm.run_structured`) turning *(new message + thread
   history)* into `ChatIntent` (`app/schemas/chat.py`): `action` (`discover|reply`), `reply` text,
   `songs` (≤5 "title artist"), `guidance` (one steering sentence), `exclude_artists`,
   `exclude_songs`, optional `include_live/include_covers/target_count`.
   - Refinements ("different artist", "more emotional", "more") reuse the last discovery's songs.
   - Vague request with no song and no history → `reply` asking for one anchor song.
   - **Gotcha:** `run_structured` uses function-calling and returns `None` when the model decides to
     chat instead of calling the tool (happens on vague messages). `understand_message` retries once,
     then raises; the prompt ends with "always answer by calling the function".
2. **Threads without a migration** — `app/services/threads.py`. A thread = `interaction_events`
   `query` events sharing `payload.thread_id`. Pre-chat runs (no thread_id) are 1-turn threads whose
   id is the run id. Provides `load_history`, `render_context` (recent 2 turns include explanations),
   `previously_recommended`, `list_threads`, `get_thread`. New event type `assistant_message`
   `{text}` stores the assistant's text per turn.
3. **Routes** — `app/api/routes/chat.py`, mounted in `app/app.py` under `/api`:
   - `POST /chat/stream` body `{message, thread_id?, include_live?, include_covers?, target_count?}`.
     SSE: `thread` → `intent` → (`step`… → `result`) | `error{message, retry_after?}`.
     Loads history *before* streaming (request DB session closes once the generator runs).
     `reply` turns end after `intent`. No-repeat: previously recommended songs in the thread are
     passed as `exclude_songs`.
   - `GET /threads` → `[{thread_id,title,updated_at,turns}]`; `GET /threads/{id}` →
     `{thread_id, turns:[{run_id,created_at,message,assistant_text,result|null,status ok|reply|failed,reaction}]}`.
4. **Orchestrator support** for steering/exclusions (`app/agents/orchestrator.py`):
   `DiscoveryState` + `run_discovery` + `stream_discovery` take `guidance`, `exclude_artists`,
   `exclude_songs`. Guidance and avoided artists are appended to the hypothesis-generation prompt
   (plus a sentence in the hypothesis system prompt treating steering as a hard requirement);
   the selection node applies `filter_excluded(...)` after `filter_input_songs`.
5. **`filter_excluded`** in `app/services/selection.py`: artist match = normalized excluded name
   contained in candidate artist (catches "Kevin Penkin & Mili"); song match = exact normalized
   "title artist".
6. **Rate limits** (`app/api/deps.py`, `app/config.py`): extracted `check_discovery_budget(redis,
   identity_id)` (used by the old dependency and by chat, since a 429 can't be raised once SSE has
   started — it is emitted as an `error` event with `retry_after`); new `enforce_chat_rate_limit`
   dependency, setting `rate_limit_chat_per_identity_per_hour = 60`. Discover turns also spend the
   existing 5/h discovery budget.
7. **Tests**: `filter_excluded` test in `tests/services/test_selection.py`; `tests/services/test_threads.py`
   (context rendering, no-repeat list). Existing orchestrator test fakes for `generate_hypotheses` needed
   `**_` added to accept the new kwargs.
8. **Docs I edited**: `docs/api-contract.md` (new "Chat" section; removed free-text/refinement from
   "Not available"), `docs/frontend-handoff.md` (update banner), `frontend/CLAUDE.md` (no longer says
   backend is non-conversational), new `docs/08-chat-layer.md`.

## What I observed in the tree afterwards (2026-10-31)
- **Still present:** `routes/chat.py`, `services/threads.py`, `agents/chat_intent.py`,
  `schemas/chat.py`, the chat prompt, `filter_excluded` in selection.py, `docs/08-chat-layer.md`,
  `tests/services/test_threads.py`, and `chat` is referenced in `app/app.py`.
- **Gone / different:** my orchestrator edits (no `guidance`/`filter_excluded` there), my `deps.py`
  edits (`check_discovery_budget`, `enforce_chat_rate_limit` missing, so `routes/chat.py` imports will
  fail), and the "Chat" section in `docs/api-contract.md`.
- **New and not mine:** `agents/hypothesis.py`, `schemas/hypothesis.py` and its prompt are staged for
  deletion (git `D`), `prompts/orchestrator_system_prompt.txt`, `agents/run_context.py`,
  `services/chat_memory.py` and `tests/services/test_chat_memory.py` exist. Someone restructured the
  orchestrator and may have built an overlapping chat-memory design. **Read these first**; if they
  already provide thread/memory logic, merge with `services/threads.py` rather than duplicating.
  With hypothesis generation removed, "where do guidance/excluded artists go" must be re-decided
  (the design above assumed they feed the hypothesis step).

## Verified (before the loss)
Live against the running stack: intent parsing (discover + artist exclusion; vague → reply; follow-up
question answered from thread history), SSE through audio → hypothesis → retrieval, `/threads`,
`/threads/{id}`; 48 unit tests passed. **Never verified:** a full discover run reaching `result` via
`/chat/stream`, or a refinement on top of a finished run — retrieval took >5 min (~80 s for one LLM
call) with the current model, pre-existing.

## Known limits
Exclusions apply after retrieval (batch can be < `target_count`; no re-retrieval). Artist exclusion
depends on the LLM naming artists. No audio upload.

## Next: the UI (not started)
ChatGPT-style app on `/chat/stream` + `/threads`: collapsible left sidebar (threads, New chat, sign
out), thread view with user bubble → assistant bubble (intent text, live stage list, then clusters/
song cards with expandable evidence), single bottom composer (Enter send, Shift+Enter newline,
options in a small popover), feedback/export CSV+JSON/Spotify under each result, light/dark, 375px
and 1440px. Keep `src/api.ts` SSE reader + 401 handling, `types.ts`, `auth.tsx`, and the StrictMode
guard in `pages/Verify.tsx`. Handle `error.retry_after`, `status:"failed"` turns, and slow (minutes)
runs. Add Vitest for the SSE parser and result states; update `docs/05-frontend.md`.
