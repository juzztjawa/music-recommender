# 5. Frontend — ChatGPT-style chat

`frontend/` — Vite + React 19 + strict TypeScript, `react-router-dom`, plain CSS, Vitest. No UI or
state library. Redesigned 2026-10-31 from a one-form page into a chat app on the backend's
`POST /chat/stream` + `GET /threads` (contract: `api-contract.md`).

## What you get
- **Left sidebar:** past conversations (from `/threads`, grouped Today / Yesterday / Previous 7 days /
  Older), **New chat**, email + sign out. Collapsible on desktop (remembered), a drawer on phones.
- **One input box at the bottom.** Type anything: songs, a link, a mood, a follow-up ("a different
  artist", "darker"), or a question about earlier picks. Enter sends, Shift+Enter = newline, a Stop
  button replaces Send while the agent works. Live/covers/songs-per-theme live in a small options
  popover; they are sent only when you change them (otherwise the agent decides, and your words win).
- **Thread view:** your message, then the assistant's turn: a live activity list (what tool the agent
  is calling, with timings; folds to "Worked for 42s · 6 steps" when done), its reply, then clusters →
  numbered songs → explanation, strength bar, expandable evidence (song title links to a YouTube search).
  Under a batch: CSV / JSON export, Export to Spotify, and the 4-way feedback + comment.
- Text-only answers (the agent asking for a song, answering "why did you pick X?") render as plain
  messages with no batch actions.

## Files
| File | Role |
|---|---|
| `src/App.tsx` | Routes: `/login`, `/verify`, then inside the shell `/` (new chat), `/t/:threadId`, `/runs/:id` |
| `src/pages/Shell.tsx`, `components/Sidebar.tsx` | Layout, thread list, collapse/drawer |
| `src/pages/Chat.tsx` | Thread loading, sending, streaming, stop/retry, scroll-following |
| `src/pages/RunRedirect.tsx` | Spotify OAuth returns to `/runs/:id?spotify=…`; finds the run's thread and forwards to `/t/:tid?run=…&spotify=…` |
| `src/chat.ts` | **Pure** turn state: `applyEvent`, `finishStream`, `turnFromStored`, error text, sidebar grouping, tool labels |
| `src/sse.ts` | Incremental SSE parser (handles chunk/CRLF splits, skips malformed frames) |
| `src/api.ts` | Typed client, 401 → logout, `streamChat`. **Kept as-is in spirit** |
| `components/Message.tsx, ToolActivity.tsx, ResultView.tsx, FeedbackBar.tsx, SpotifyExport.tsx, Composer.tsx` | UI pieces |

Kept from before: `auth.tsx`, `api.ts` (401 handling, blob downloads), `Verify.tsx` (StrictMode guard
for the single-use link). Removed: `Discover.tsx`, `History.tsx`, `Progress.tsx` (history is the sidebar).

## Behaviours worth knowing
- **No fixed step list.** The backend is a tool-calling agent: events are `tool` started/done/error keyed
  by `call_id` (they can overlap). Known tool names get friendly labels; unknown ones still render.
  A tool `error` is shown as "hit a snag, carrying on" (the audio tool always does today — normal).
- **Slow runs.** Searches take minutes (there is no server time limit; the retrieval agent is bounded by a tool-call budget instead). The activity header shows elapsed time and,
  after 45 s, a "this takes a few minutes" hint. Nothing assumes a quick finish.
- **Limits.** 429 before streaming (message limit) and the `error` event with `retry_after` (discovery
  budget) both show "Try again in about N min" with no retry button; other errors offer **Try again**.
  Any 401 → login.
- **New chat → URL.** The first `thread` event navigates to `/t/<id>` without reloading the live turn.
- **Stored threads** show failed turns as "this answer wasn't saved". Live tool activity isn't stored, so
  reopened threads show the reply and batch only.
- Light/dark follow the OS; reduced motion respected; works at 375 px (drawer sidebar) and 1440 px.

## Verified — and not
✅ `npm run build` (strict TS) and `npm test` (20 tests: SSE parser incl. 1-byte chunks/CRLF/malformed
frames, turn reducer incl. overlapping tool calls, text-reply vs batch, errors with `retry_after`, stored-turn
mapping, thread grouping, and rendering of loading / tool list / batch / empty cluster / text reply /
429 / generic error / failed states).
✅ In headless Chrome against the real backend (auth, `/threads`, history sidebar) with a **mock SSE
server** for the chat stream: empty state, live activity, finished batch, text reply, rate-limit error,
dark/light at 1440 px, 375 px with drawer; no console errors.
❌ **Not verified:** a real agent run end to end (the backend agent was never run against the real LLM and
searches take minutes); Spotify connect/export against Spotify; CSV/JSON download in a browser; reopening a
real stored batch from the sidebar beyond the old text-only threads; screen-reader behaviour.

## Review checklist
- Open `docs/api-contract.md` Chat section beside `src/chat.ts` — the event handling mirrors it.
- Try: new chat → send → watch activity → feedback; "a different artist" follow-up in the same thread;
  Stop mid-run; reload mid-thread; sign out/in.
- Known gap: no delete/rename for threads (backend has no endpoints).
