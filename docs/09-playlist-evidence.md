# 9. Playlist evidence (user-built Spotify playlists)

Source: `backend/app/clients/spotify_playlists.py`, `backend/app/services/playlist_scoring.py`,
`backend/app/services/playlist_discovery.py`, the `find_playlist_candidates_tool` in
`backend/app/tools/retrieval.py`, and `backend/app/prompts/retrieval_system_prompt.md` (v3).

## Why
The product's value is *human taste*, not catalog metadata. Reddit was the planned opinion source but is
shelved (account suspended, appeal dead — see `backend/archive/reddit/README.md`). A user-built playlist is
the next best human signal: its author put these songs next to each other on purpose. Spotify's own
editorial playlists are deliberately down-weighted because they reproduce Spotify's list, which is what
this app is meant to differ from.

## What it does
```
seeds + vibe phrases ─► search playlists (≤6 queries) ─► rank, read ≤15 playlists (≤200 tracks each)
                    ─► score songs that co-occur with the seeds ─► top N with evidence
```
The retrieval agent calls it **once, first**, with the cluster's input songs; the candidates it returns
become the base set that other providers corroborate (prompt v3).

## Noise cleaning — mostly code, not prompt
| Step | Rule | Why |
|---|---|---|
| Anchor | Playlist counts only if it contains a seed song (weight 1.0, +0.25 per extra seed, max +0.75) or another song by a seed artist (0.35) | The author already put your song in this playlist; this is the similarity guarantee |
| Locality | Contribution halves every 8 positions from the seed (floor 0.15) | Playlists are sequenced by vibe; track 200 says little about track 5 |
| Owner cap | One owner counts once per track (their best playlist) | 20 near-identical playlists by one person must not look like consensus |
| Weights | Spotify-owned ×`PLAYLIST_EDITORIAL_WEIGHT` (0.25); size factor (peak 15–150 tracks, <8 ignored, big dumps discounted); +≤30% if playlist name/description matches the vibe words | Prefer user-built, coherent lists |
| Rarity | Score × (1 + ln((owners+1)/(owners_containing_track+0.5))) | Globally popular songs would otherwise win every query |
| Support | Needs ≥2 independent owners; if fewer than 10 such songs exist, single-owner songs are kept, score ×0.5, `weak: true` | Don't return nothing on niche seeds, but say so |
| Artist caps | ≤4 songs per artist, ≤2 for a seed artist | Live run: without this, results were mostly the seed artist |
The LLM's job is the last step only: judge the survivors against the hypothesis, merge with other providers'
evidence, set `recommendation_strength`. The numbers above live in `playlist_scoring.py` constants and are
**starting values, not tuned** — see Review checklist.

## Spotify limits (what we know)
Spotify publishes **no numeric limit**. Calls are counted per app in a rolling 30 s window; exceeding it gives
`429` + `Retry-After`. Dev-mode apps also share an undisclosed per-developer-account quota, and are limited to
5 allowlisted *logged-in* users (client-credentials search is not tied to a user). Playlist search returns
**max 10 per call**. Worst case per cluster = 6 searches + 15 playlists × 2 pages = **36 calls**;
the live run used 6 searches + 15 reads in ~5 s with no 429. Mitigations in the client: concurrency 4
(`SPOTIFY_PLAYLIST_CONCURRENCY`), one `Retry-After` retry (≤10 s) then `SpotifyRateLimited`, in-process cache
(searches 1 h, playlists 6 h). Tunables: `PLAYLIST_MAX_SEARCHES/FETCHES/TRACKS`.

## Verified vs not
- **Verified live (2026-11-01):** playlist search; `/playlists/{id}/items` returned tracks of playlists
  owned by other users; end-to-end run for seeds *Let Down – Radiohead* + *Lover, You Should've Come Over –
  Jeff Buckley* returned 25 varied songs (Mazzy Star, The Smiths, Sufjan Stevens, Mitski, Chris Isaak…),
  with some noise (e.g. Roar, Conan Gray, Paramore).
- **Unit-tested:** each filter above, the client's 429/403/null handling and caching, discovery with a stubbed client.
- **Not verified:** behaviour with the real supervisor LLM calling this tool; quality on non-English or niche
  seeds (the live sample leaned toward Hindi-pop playlists for generic queries); whether Spotify keeps allowing
  third-party playlist reads — its Feb 2026 changelog says non-owned playlists return metadata only. The
  client treats a 403/404 per playlist as "unreadable" and carries on; if all are unreadable the tool returns
  an empty list and the agent falls back to other providers.

## Review checklist
- Are 8-position half-life, 2-owner minimum and the 0.25 editorial weight right? They were chosen by reasoning
  plus one live sample, not by measurement. A small labelled eval (seeds → songs you'd accept) is the fix.
- Playlist *search* matches names/descriptions only, so seeds help just through their artist/title words; a
  seed with no playlists named around it yields little. Is that acceptable for obscure songs?
- No tag/audio similarity check yet on the survivors (Last.fm tags or the audio caption could drop outliers
  like pop-punk songs in a mellow cluster). The agent has the Last.fm tool but isn't told to use it for this.
- Cache is per-process memory: restarts and multiple workers each refetch. Move to Redis if call volume matters.
- Playlist contents are third-party user content; titles/descriptions are passed to the model only through
  names of example playlists — check that is acceptable.
