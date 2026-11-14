# Frontend handoff — redesign into a ChatGPT-style interface

You are taking over the **frontend only** (`frontend/`). The backend is done and stays as is.
Read this file, then `docs/api-contract.md`, then `SETUP.md` to run it.

## 1. The product in one paragraph
Orchestra is an evidence-driven music discovery engine ("Rediscover the feeling that made you
love a song"). The user chats in free text (songs, links, or a description of the feel they want); the backend works out why it appeals, searches several
sources, and returns recommendations each with a human-readable explanation and the evidence behind
it. Results can be exported (CSV, JSON, Spotify playlist) and the user can rate each batch.

## 2. Why this handoff
The current UI (React, a single form page) works but the owner dislikes it. They want a
**ChatGPT-like interface**. The existing app is a functional first pass, not a design to preserve.

## 3. What to build (the owner's intent)
The backend now supports real conversation (see §4), so build it as one:
- **Left sidebar:** conversations from `GET /threads`, a "New
  discovery" button, sign out. Collapsible; on mobile a drawer.
- **Main thread:** per run, a **user message** followed by an **assistant message** that first shows
  the agent's live activity (SSE `tool` events), then its `reply` text, then the result: one section
  per theme (cluster), song cards with explanation and expandable evidence. Messages in the same
  `thread_id` form one thread; the composer continues that chat.
- **Composer at the bottom**, like ChatGPT: type anything and send (Enter sends, Shift+Enter newline). Options (live/covers/count) tucked
  into a small popover/menu, not a big form.
- **Under each assistant message:** feedback (4 reactions + optional comment), export CSV/JSON,
  Export to Spotify.
- Opening a thread from the sidebar renders every turn from `GET /threads/{id}`.
- Light/dark following the OS; works at phone width; keyboard-friendly (Enter to send,
  Shift+Enter for newline).

Visual direction is yours to choose — make it feel considered, not like a default template. No
design assets exist.

> **UPDATE 2026-10-31:** the backend is now conversational (`POST /chat/stream`, `GET /threads`,
> see `api-contract.md`). Free text, refinement, no-repeat and threads are real; the table below is
> outdated for those rows (audio upload is still not built). The owner also lifted "don't edit
> backend" for the chat layer. Build the UI on `/chat/stream` with ONE input box.

## 4. What the backend does and doesn't do
The backend is a **tool-calling supervisor agent** (restructured 2026-10-31; it was a fixed pipeline
before). It takes one free-text message and decides for itself which tools to use. So the chat
metaphor is real:

| Chat behaviour | State |
|---|---|
| Type free text: song names, track links (Spotify/YouTube/YouTube Music), or a description of the music | **Supported** — send it as `message`. |
| Follow-ups ("darker", "more like the second one", "hidden gems") | **Supported** — send the previous turn's `thread_id`; the agent reads the thread's earlier turns. |
| No repeats within a chat | **Supported** — songs recommended earlier in the thread are skipped; "different artist" is honoured. |
| Streaming of what the agent is doing | **Supported** — `tool` events (see `api-contract.md`); no fixed step list. |
| Upload an audio file | **Not built.** The agent finds songs on YouTube from titles/links. |
| Sidebar of past conversations / reopen one | **Supported** — `GET /threads`, `GET /threads/{id}` (turn status `ok` / `reply` / `failed`). |
| Text-only answers ("why did you pick that?") | **Supported** — a turn can end with only `reply`; `clusters` is empty. |
| Apple Music links | Not supported (the agent will ask for title + artist). |

Also true today:
- Audio captioning is **not hosted** (`MUSIC_FLAMINGO_ENDPOINT_URL` unset), so every audio step
  reports an error and the agent continues from titles. Show it unobtrusively, not as a failure.
- A run takes tens of seconds to a couple of minutes (not measured with the current model);
  streaming progress is essential. There is no server time limit by default; if one is ever set, the turn ends with a normal `message` + `result` explaining it, not an error.
- The agent can answer without recommendations (nothing found / couldn't identify a link): `clusters`
  empty and `reply` explains. Render `reply` as the assistant's message in every case.
- Rate limit: 5 discoveries/hour per user, 40/day globally → HTTP 429 with `Retry-After`.
- A thread turn can have `status:"failed"` (no answer stored); show it as a failed turn.
- The backend returns no per-track URLs; the current UI links titles to a YouTube *search*. Spotify
  links exist only after a Spotify export.
- The agent sees the thread's last 6 turns.

## 5. What exists (`frontend/`)
Vite + React 19 + TypeScript (strict) + `react-router-dom`, plain CSS. Dev server proxies `/api` to
`localhost:8000`.

**Keep (logic is sound and tested against the backend):**
- `src/api.ts` — typed API client; 401 → logout handler; `streamDiscovery(message, chatId, …)` async
  generator that reads the SSE stream by hand (needed because `EventSource` can't POST or send auth headers);
  authenticated blob downloads for exports.
- `src/types.ts` — response types mirroring the backend.
- `src/auth.tsx` — auth context, token in `localStorage`.
- `src/pages/Verify.tsx` — single-use token exchange; has a ref guard against React StrictMode
  running the effect twice (don't remove it or the link burns on the first call).

**Replace freely** (a minimal textarea + tool-progress version exists so the app still works):
`src/pages/Discover.tsx`, `History.tsx`, `Login.tsx` layout, `src/components/*`,
`src/styles.css`, routing structure.

## 6. Features that must keep working
Magic-link login (button shown when backend `ENVIRONMENT=test`) · streamed agent activity ·
follow-up messages via `thread_id` · result rendering with explanations and evidence · feedback (`POST /feedback`) · CSV/JSON export
· Spotify connect + export (including the `?spotify=connected|denied|error` return) · run history ·
429 and 401 handling · aborting a stream when leaving the page.

## 7. Rules
- Only touch `frontend/` and docs. Don't edit `backend/`, migrations, or `docker-compose.yml`.
- Don't commit unless the owner asks. Never put secrets in the frontend.
- Types stay strict; `npm run build` must pass (it runs `tsc --noEmit`).
- There are **no frontend tests** today. Add at least unit tests for the SSE parser and the result
  rendering states (loading, error, 429, empty cluster, failed run), using Vitest.
- Verify in a real browser against the running backend, not only by building. Say plainly what you
  could not verify.
- When done, update `docs/05-frontend.md` (what/why/tradeoffs/verified vs not, review checklist) —
  the owner reviews markdown, not source. If setup changes, update `SETUP.md` and its changelog.

## 8. Running it
See `SETUP.md`. Short version: `docker compose up -d`, `cd backend && uv run main.py`,
`cd frontend && npm run dev`, open http://localhost:5173. With `ENVIRONMENT=test` the login page
gives an "Open sign-in link" button (no email server exists).

## 9. State of verification (be skeptical)
- The backend orchestration was rewritten (supervisor agent) and is verified with a *scripted* model
  through the real routes; it has **not** been run against the real LLM. `glm-5.3-flash:cloud`
  tool-calling quality is the main open risk — if runs misbehave, look at the trace in MLflow
  (http://localhost:5000) and `interaction_events`.
- The previous agent never ran this UI in a browser itself; the owner has viewed the login and
  discover pages (screenshots) and found the design poor.
- The LLM model was changed from a retired one (`deepseek-v4-flash:0731`, HTTP 410) to
  `glm-5.3-flash:cloud`. It answers a plain prompt but **has not been verified with the retrieval
  agent's tool calling**; if discovery fails at the retrieval step, that is the first suspect, and the
  cause is in `interaction_events` (event_type `error`) or MLflow at http://localhost:5000.
- Spotify export has only been tested with mocked Spotify responses.

## 10. Definition of done
All features in §6 work in a browser; layout works at 375px and 1440px in light and dark; no console
errors; `npm run build` and the new tests pass; `docs/05-frontend.md` updated; a list of anything that
needs backend changes in `docs/backend-requests.md`.
