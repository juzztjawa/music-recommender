# 08 — Chat layer (backend)

> **Superseded in part (2026-10-31).** The intent step (`chat_intent.py` + prompt), the `intent`/`step` SSE
> events and the orchestrator's `guidance`/`exclude_*` parameters were replaced by the supervisor agent
> (doc 2): `/chat/stream` now hands the raw message and thread history to it. **Still in use:** threads
> (`services/threads.py`, `/threads`), `ChatRequest`, `filter_excluded` (now reachable through
> `select_and_diversify(exclude_artists=…)`), the chat rate limit. The rest of this document describes
> the earlier design and is kept for the record.

**Why:** the UI took 1–5 song titles one by one; the owner wants to talk to the agent in one box
("songs like X but a different artist"). That needs the backend to understand free text and remember
the conversation.

**What was built**
- `app/agents/chat_intent.py` + `prompts/chat_intent_system_prompt.txt`: one structured LLM call
  turns *(message + thread history)* into `ChatIntent` — `discover` or `reply`, reference songs,
  steering sentence, excluded artists/songs, option overrides. Retries once if the model returns no
  function call (it does for vague messages — seen live).
- `app/services/threads.py`: threads live in `interaction_events` (`payload.thread_id` on the
  `query` event) — **no migration**. Old runs show up as 1-turn threads.
- `app/api/routes/chat.py`: `POST /api/chat/stream`, `GET /api/threads`, `GET /api/threads/{id}`.
- Orchestrator now accepts `guidance`, `exclude_artists`, `exclude_songs`: guidance/exclusions go
  into hypothesis generation; `filter_excluded` (selection.py) drops excluded artists and anything
  already recommended in the thread, deterministically.
- Rate limits: new 60 msg/h/user; a discover turn still spends the 5/h discovery budget.

**Trade-offs / known limits**
- A pure mood with no song and no earlier songs gets a clarifying reply (pipeline needs an anchor).
- "Different artist" exclusion relies on the LLM naming artists; the filter is deterministic after that.
- Excluding after retrieval can yield fewer than `target_count` songs (no re-retrieval).
- Retrieval is slow with the current model (observed ~80 s for the LLM call alone, run >5 min);
  pre-existing, not caused by chat.

**Verified:** 48 unit tests pass (new: `filter_excluded`, thread context rendering); live against the
running stack: intent parsing (discover + exclusion, vague→reply, follow-up question using thread
history), SSE up to retrieval, `/threads`, `/threads/{id}`. **Not verified:** a full discover run to
`result` through `/chat/stream` and a refinement discover on top of a finished run (retrieval too slow
to finish within my test window).

**Review checklist:** read `chat_intent_system_prompt.txt`; `routes/chat.py` event order; decide whether
exclusions should trigger a re-retrieval.
