# 4. Feedback, history & export (Phase 8)

Files: `models/feedback.py`, `schemas/feedback.py`, `services/runs.py`,
`services/export.py`, `api/routes/feedback.py`, `api/routes/runs.py`,
migration `c41b8e07d3a9_feedback.py`, tests `tests/services/test_export.py`.

## The key decision: a "run" is identified by `run_id`
The log already grouped events by a per-request `run_id`, but the client was never told
it. Now both discover endpoints return it (`DiscoveryResult.run_id`; in the stream it's
inside the `result` event's `data`). Everything in this phase hangs off that id.

## Where a past batch lives
No new "batches" table. The batch is the `recommendation` event already in
`interaction_events`. History and export read it back. **Why:** one source of truth, no
duplicate storage. **Cost:** reads parse JSONB, and the stored shape must stay compatible
with the export code.

- The streaming route used to store the whole SSE envelope (`{"type":"result","data":…}`).
  It now stores the bare result so streamed and non-streamed runs look identical;
  `get_run_result` also unwraps the old envelope for any rows already written.

## Feedback (FR-13)
- Four reactions: `loved_it | pretty_good | mixed | missed`, optional comment (≤2000 chars).
- **Batch-level, not per-song** (FR-13.1).
- Upsert on `run_id`: changing your mind overwrites, doesn't duplicate.
- Also written to the interaction log as a `feedback` event.
- **Does not change recommendations.** The requirements allow in-session adaptation
  (FR-13.2) but forbid cross-session effects; since there are no follow-up requests yet
  (doc 6), there's no session to adapt. Feedback is currently **stored only**.

## History & export (FR-15/16)
- `GET /runs` — your last 20 runs: songs, time, your reaction.
- `GET /runs/{id}` — the stored batch.
- `GET /runs/{id}/export?format=csv|json` — attachment download. CSV columns:
  cluster, title, artist, strength, variant, sources, explanation. JSON is the raw batch.
  Each export is logged as an `export` event.
- CSV uses Python's `csv` module, so commas/quotes in titles are escaped (tested).

## Security: ownership
Every lookup filters on `identity_id == caller`. Another user's `run_id` returns **404,
not 403** (doesn't reveal that it exists). Verified live: user B got 404 for feedback and
export on user A's run.

## Spotify playlist export (added 2026-10-31)
Originally deferred; built after it was asked for. Files: `services/spotify_oauth.py`,
`services/spotify_export.py`, `api/routes/spotify.py`, `components/SpotifyExport.tsx`.

**Why a separate login:** search uses app-only Client Credentials (no user). Writing to a
playlist needs the user's consent, i.e. the Authorization Code flow.

**Flow:** button → `GET /spotify/connect` returns the Spotify consent URL → browser goes to
Spotify → Spotify redirects to `GET /spotify/callback` → we swap the code for tokens, store them,
and redirect back to the run (`?spotify=connected`) → user presses Export →
`POST /runs/{id}/export/spotify`.

**Decisions**
- `state` is a random single-use value in Redis (10 min) mapping the callback to the identity —
  the callback is a bare browser redirect with no JWT. Forged or replayed state is rejected (tested).
- Tokens: JSON encrypted with Fernet (key = SHA-256 of `JWT_SECRET`) in the existing
  `identities.spotify_oauth_token` column. Refreshed ~60 s before expiry; if Spotify rejects the
  refresh the tokens are cleared so the UI offers "connect" again instead of failing forever.
- Hand-written with `httpx` (3 calls) rather than spotipy's `SpotifyOAuth`, which is built for one
  user with a token file on disk. spotipy remains for catalog search.
- Matching is strict: a result must match the title exactly (normalised) and have an overlapping
  artist. Unmatched songs are returned in `not_found` rather than guessed — a wrong song in your
  playlist is worse than a gap. Expect some misses (covers, alternate titles).
- One private playlist per export; 100 tracks per add request (Spotify's limit); 429 is retried.
- Uses Spotify's **February 2026** endpoints: `POST /me/playlists` and `POST /playlists/{id}/items`
  (the old `/users/{id}/playlists` and `/tracks` are gone for dev-mode apps).
- Redirect URI must be `http://127.0.0.1:8000/api/spotify/callback` — Spotify rejects `localhost`.

**Constraints you can't code around:** dev-mode apps need the app owner on Premium and an allowlist
(max 5 users). Fine for a single tester; it is the reason this can't go public without Spotify's
extended-quota approval (currently organisations only).

**Not yet verified:** a real consent + export against Spotify. Everything is tested with Spotify's
HTTP calls mocked (matching, retry, refresh, state handling) and the routes were exercised against
real Postgres/Redis, but nobody has clicked through Spotify's login yet.

## Verified
42 unit tests pass (export, Spotify OAuth and export). Against a real Postgres: migration applies;
feedback create → overwrite → appears in history; cross-user access 404; invalid
reaction 422; CSV/JSON download headers; a streamed run (LLM stages stubbed) is
retrievable and exportable by its `run_id`.

## Review checklist
- Export/history parse a JSONB blob — if `RecommendedSong` fields change, old runs may
  stop exporting cleanly. Acceptable, or add a schema version?
- `GET /runs` lists runs whose discovery *failed* too (they have a `query` event but no
  batch); opening one shows "Couldn't load that run." Fine, or filter them out?
- No pagination on history (fixed 20).
