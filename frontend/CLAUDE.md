# Frontend agent instructions

You are redesigning this frontend into a ChatGPT-style interface.

**Read first, in order:** `../docs/frontend-handoff.md` (the brief — scope, limits, rules, definition
of done) → `../docs/api-contract.md` (every endpoint and the SSE event shapes) → `../SETUP.md`
(how to run the stack).

Essentials:
- Touch only `frontend/` and `docs/`. Don't edit `backend/` unless the owner asks (the chat layer was added by the owner's request). Backend gaps go in `docs/backend-requests.md`.
- Stack: Vite + React + strict TypeScript. `npm run dev` (http://localhost:5173, proxies `/api` →
  :8000), `npm run build` must pass.
- Keep `src/api.ts` (SSE reader, 401 handling), `src/types.ts`, `src/auth.tsx`, and the StrictMode
  guard in `src/pages/Verify.tsx`.
- The backend IS conversational now (2026-10-31): `POST /chat/stream` takes one free-text message
  (+ `thread_id`), `GET /threads[/id]` gives history. Use one input box; no per-song fields. Audio
  upload still doesn't exist — don't fake it.
- Don't commit unless asked. Update `docs/05-frontend.md` when finished; the owner reviews markdown.
