# Orchestra — code review docs

These docs exist so the code can be reviewed by reading prose instead of source.
Each one explains **what a part does, why it was built that way, and what to
challenge**. Every doc ends with a "Review checklist" — if an answer there
surprises you, that's where to open the actual code.

| # | Doc | Read it to understand |
|---|-----|-----------------------|
| 1 | [System overview](01-system-overview.md) | The whole thing in one page: flow, layers, repo map |
| 2 | [Discovery: supervisor agent](02-discovery-pipeline.md) | The agent, its tools, what is LLM vs code, chat memory |
| 3 | [API, auth, data & limits](03-api-auth-data.md) | Endpoints, magic-link login, tables, interaction log, rate limiting |
| 4 | [Feedback, history & export](04-feedback-history-export.md) | Phase 8 |
| 5 | [Frontend](05-frontend.md) | Phase 9: the React SPA and how it consumes the SSE stream |
| 6 | [Risks & open items](06-risks-and-open-items.md) | What is **not** built, known weak spots, decisions only you can make |
| 7 | [Observability](07-observability.md) | MLflow + event log: how to see an agent run |
| 8 | [Chat layer](08-chat-layer.md) · [its handoff note](chat-layer-handoff.md) | Threads and the earlier intent design (partly superseded by the supervisor) |
| – | [Frontend handoff](frontend-handoff.md) · [API contract](api-contract.md) | Brief and API reference for the agent redesigning the UI |

**To run it locally: [SETUP.md](SETUP.md)** (kept up to date as setup changes).

Suggested order: 1 → 6 → 2 → whichever of 3/4/5 you care about.

## Status at the time of writing (2026-10-28)

| Phase | Scope | State |
|---|---|---|
| 1–7 | Skeleton, auth, retrieval agent, selection, audio, orchestrator, explanation, SSE, rate limit, step logging | Done |
| 7b | MLflow tracing, full tool/LLM-call logging, evals | **Not built** (deliberately skipped, see doc 6) |
| 8 | Feedback, run history, CSV/JSON export | Done (CSV/JSON + Spotify playlist export) |
| 9 | React SPA | Done |
| 10 | Tests + deploy | Not started |

How these were verified is stated in each doc; what was *not* verified is in doc 6.
