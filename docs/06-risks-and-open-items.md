# 6. Risks & open items

> Updated 2026-10-31 after the supervisor-agent restructure (doc 2). Free-text input, track links,
> threads, follow-ups and no-repeat now exist; the table below reflects what is still missing.

Read this before trusting the "Done" labels.

## Not built (requirements that exist but have no code)
| Item | Requirement | Note |
|---|---|---|
| **Phase 7b — observability & evals** | FR-19 (tool calls), SRS §20 | The planned MLflow tracing, per-tool/LLM-call logging and golden-set evals were **skipped** to reach the frontend, though the plan said to do them first. Today you cannot see *what the retrieval agent actually did* — only stage progress and the final batch. This is the biggest gap for judging quality. |
| **Real email sending** | FR-18 | Dev stub prints the link. |
| **Phase 10** | – | No CI, no deploy config verified, no frontend tests. |

## The supervisor agent has not run against the real LLM
The restructure is verified with a scripted model through the real loop, tools, routes, Redis and
Postgres, but never with `glm-5.3-flash:cloud`. Its tool-calling and prompt-following are the top
risk (doc 2). Also still unbuilt: cached song analyses/evidence (SRS §17), Apple Music links, audio
upload, YouTube playlist export (optional), an explicit "insufficient evidence" UX beyond the agent's
reply (FR-17), and enforcement of the ~60 s budget (no wall-clock limit by default; the retrieval agent is bounded by a tool-call budget).

## Never run end-to-end by me
The whole pipeline was exercised live in earlier phases (per PROJECT_STATUS), but in this
work session the LLM/provider stages were **stubbed**. I did not run a real discovery
through the new UI. Provider credentials and the Music Flamingo endpoint are
environment-dependent.

## Reddit (via Composio): works live, not yet exercised by the agent
A live search and thread read succeeded on 2026-11-07 (doc 10), but no real discovery request has used the tools
yet. The managed Reddit app is shared with other Composio users, so throttling under load is possible and untested. Without
Reddit, opinion evidence rests on user-built Spotify playlists (doc 9) plus Last.fm tags; those playlist reads
work today but contradict Spotify's Feb 2026 changelog and could be switched off.

## Spotify export: untested against the real service
Built and unit-tested with mocked HTTP; the first real consent + export is still to do (doc 4).

## Known weak spots
1. **Quality is unmeasured.** The agent scores its own picks; no eval set; the only
   quality signal will be user feedback, which is stored but not analysed anywhere.
2. **Single model, no real fallback** (primary == fallback). A model outage = outage.
3. **A run costs ~3–4 LLM calls + a YouTube download + up to many provider calls**, and a
   failed run still consumes a rate-limit slot.
4. **`request.client.host` rate-limiting** breaks behind a reverse proxy.
5. **`localStorage` JWT, 60-min expiry, no refresh** — see doc 3.
6. **Failed runs appear in History** (see doc 4).
7. **Legal/licensing:** YouTube audio download (ToS) and Music Flamingo's non-commercial
   NVIDIA licence — both noted in the design as "check before real testers".

## Decisions only you can make
1. Do 7b (observability) **before** inviting testers, or accept flying blind? Recommended:
   before — it is the only way to debug a bad recommendation.
3. Is session refinement (FR-14/15) in scope for the first demo?

## Suggested next order
1. Run it once for real in a browser and fix what breaks.
2. Phase 7b (at least tool-call + LLM-call logging into `interaction_events`).
3. FR-14/15 refinement.
4. Real email sender → deploy.
