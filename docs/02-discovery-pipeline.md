# 2. Discovery: the supervisor agent

Source: `backend/app/agents/orchestrator.py`, `backend/app/tools/orchestrator.py`,
`backend/app/prompts/orchestrator_system_prompt.md`, `backend/app/agents/run_context.py`.

> **History:** until 2026-10-31 this was a hardcoded five-node pipeline (audio → hypothesis →
> retrieval → selection → explanation) taking only a list of song titles. That contradicted the
> architecture (a tool-calling supervisor) and the requirements (free text, URLs, follow-ups). It
> was replaced by what is described here. See the "Review checklist" for what is still unproven.

## The shape
One **supervisor agent** (`langchain.agents.create_agent`) receives the user's free-text message,
the chat's history and the default options. It decides which tools to call. **The stage order lives
in its system prompt, not in code**: understand → identify → listen → hypothesise → retrieve → select
→ explain → reply. Changing the flow means editing a text file.

```
message ─► Supervisor (LLM, system prompt = the flow)
              │ calls tools, may batch independent calls
              ├─ get_session_history   earlier turns of this thread (FR-14)
              ├─ resolve_song          title / Spotify / YouTube link → title + artist (FR-1.1)
              ├─ analyze_audio         yt-dlp + audio model → caption (input songs only, FR-3.4)
              ├─ retrieve_candidates   sub-agent: 6 provider tools + evidence scoring (FR-6/7/9)
              ├─ select_and_diversify  deterministic rules, FR-8/10/15
              └─ write_explanations    LLM call, evidence-grounded (FR-12)
           ◄─ final message (`reply`);  result is assembled from tool state, not from model text
```

## What is LLM-driven and what is code
| Piece | Kind | Why |
|---|---|---|
| Understanding the message, following the flow, writing hypotheses, clustering | Supervisor LLM | Needs judgment; this was a single hidden call before |
| Retrieval (which providers, how hard, scoring each candidate) | Nested tool-calling agent | Unchanged; now exposed to the supervisor as one tool |
| Selection (merge, drop input song, drop live/covers, rank, ≤3 per artist, skip repeats, trim) | Plain Python tool | Fully specified rules; testable; an LLM must not hold hard constraints over 50–100 items |
| Explanations | LLM call inside a tool | One call per cluster |
| Audio (find on YouTube, caption) | Plain code inside a tool | Fixed procedure; best-effort; never fatal |

## Decisions
- **Prompt owns the order; tools own the preconditions.** `select_and_diversify` on an unknown
  cluster returns an error the agent reads and recovers from; it cannot corrupt state.
- **Bulky data stays out of the model's context.** `retrieve_candidates` stores 50–100 candidates in
  a per-request `RunContext` and returns `{cluster_id, count}`. Selection reads them back from there.
- **The result is assembled from tool state**, never from the model's text, so recommendations can't
  be hallucinated into the response. The model only writes `reply`.
- **Thread memory** (`services/threads.py`, built by the chat-layer agent): threads are reconstructed from
  `interaction_events` (`payload.thread_id`), no extra table. The route loads the last 6 turns and the
  supervisor reads them via `get_session_history` and skips songs already recommended (FR-14/15). It is
  read only inside the thread that wrote it (no cross-session effect).
- **Limits:** supervisor recursion limit 40 (≈20 tool rounds); the **retrieval sub-agent has its own budget** — at most 24 tool calls (then it is told to answer with what it has) and 8 model rounds as a hard backstop (`retrieval_max_*` in config). There is **no wall-clock limit by default**; `DISCOVERY_TIMEOUT_SECONDS` is optional and, if set, ends a request gracefully with a message and whatever finished (never an error). Why: live, with no budget the retrieval agent kept searching for 10 minutes without answering; ~91% of that time was model latency, the searches took under a second each.
- **Model fallback:** if the primary model fails *before any output*, retry once on the fallback
  model; after output has started it raises (replaying would repeat tool calls).
- **Streaming:** `agent.astream(stream_mode="updates")` is translated to `tool started/done/error`,
  `message`, `result` events. No fixed step list exists any more.
- **Tracing:** unchanged — MLflow root span per request, DB recorder for every tool/LLM call.
  The supervisor's own LLM turns now show up as `llm_call` events too.

## Review checklist
- **Never run against the real LLM yet.** Tested with a scripted model through the real agent loop,
  tools, run state, routes, Redis and Postgres. Whether `glm-5.3-flash:cloud` follows the prompt's
  flow, calls tools with valid arguments and recovers from errors is **unproven** — run one real
  request and read the trace. If it loops, the retrieval budget and recursion limits are what stop it.
- Is it acceptable that the agent can, in principle, skip a stage? The prompt forbids it and tools
  refuse out-of-order calls, but nothing forces a stage. If it misbehaves, the fix is a stricter
  prompt first, a code guard second.
- **Retrieval restarts:** if the retrieval agent fails and the fallback model is the *same* model, it is not retried (a retry replayed the whole search from zero and doubled the run). A distinct fallback model gets one retry.
- Cost/latency: more LLM turns than the fixed pipeline (each tool round is a model call).
- `already_recommended` matching is by normalised title + artist; a different release of the same
  song can slip through.
- Free-text clarity: the agent is told not to ask clarifying questions except when it can't produce
  recommendations. Confirm that is the behaviour you want.
- The old chat-intent step (one LLM call that classified each message, then fed a fixed pipeline) was
  replaced by the supervisor; its files have been deleted.
- Still unbuilt: URL handling for Apple Music, audio upload, cached song analyses (`§17`).
