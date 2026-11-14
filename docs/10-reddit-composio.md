# 10. Reddit via Composio

Source: `backend/app/clients/reddit_composio.py`, `search_reddit_tool` / `read_reddit_thread_tool` in
`backend/app/tools/retrieval.py`, `backend/app/prompts/retrieval_system_prompt.md` (v4),
`backend/scripts/composio_reddit_check.py`.

## Why this exists
Reddit is where listeners argue about and recommend music, which is the opinion evidence the app lacks.
Direct Reddit API access needs our own developer credentials, and that account is suspended (appeal dead).
Composio runs a **managed Reddit OAuth app** (its docs: "you sign in with your normal Reddit account and
approve access"), so the backend calls Reddit through Composio with one stored login. The earlier PRAW
client is kept in `backend/archive/reddit/` only as a fallback if own credentials ever return.

## How it works
```
retrieval agent ─► search_reddit_tool ──┐                         ┌► REDDIT_SEARCH_ACROSS_SUBREDDITS
                └► read_reddit_thread ──┴─► reddit_composio.py ──►│  (Composio, user_id=COMPOSIO_USER_ID,
                                           cache · cap 2 · 20 s   └► REDDIT_RETRIEVE_POST_COMMENTS   managed OAuth)
```
- Offered to the agent only when `COMPOSIO_API_KEY` is set (same rule as every provider).
- **Parameter names are discovered, not assumed.** They could not be read without an API key, so the client
  fetches each tool's input schema once and maps our fields (query, subreddit, limit, sort, time, post id) onto
  whichever candidate names exist (`_ALIASES`). A required parameter it cannot map fails with a message naming it.
- Output parsing walks the response for anything shaped like a post or a comment instead of assuming one layout.
- Calls run with `dangerously_skip_version_check=True` (latest tool version) because tolerant parsing plus an LLM
  consume the output; pin a dated version via the SDK if you later parse strictly.
- Comments are sorted best-first and truncated (`REDDIT_MAX_COMMENT_CHARS`, 400) so a thread costs few tokens.

## How the agent uses it (prompt v4)
Playlist candidates remain the base set (doc 9). Reddit corroborates and enriches: ≤3 searches and ≤2 thread
reads per run, scoped to subreddits like musicsuggestions / ifyoulikeblank / indieheads; read the 1–2 best threads
because the recommendations are in the comments; a song named by several commenters, or also in the playlist
candidates, is strong evidence (`community_discussion`, source `reddit`); one lone mention is weak. On rate limit or
error the agent must not retry and continues without Reddit.

## Safeguards
- **Untrusted text:** post and comment bodies are third-party content and a prompt-injection vector. Both tool
  descriptions and the prompt say it is data only; the agent has no write tools and the Composio tools exposed are
  read-only (posting/voting/deleting tools are not wired).
- **Rate limits:** Reddit limits per OAuth app/account and the managed app is shared with other Composio users
  (Composio's docs list "a separate rate-limit quota" as a reason to bring your own app). The client allows 2
  concurrent calls, caches (searches 1 h, threads 6 h) and raises `RedditRateLimited` instead of retrying.
- **Empty-error failures:** a live run (2026-11-07) saw two Reddit calls fail with no error message (10 s and 5 s) while identical calls succeeded minutes later. The client now retries such a failure once after 2 s, and any final failure logs and reports Composio's raw response instead of "unknown error". Cause unconfirmed (suspected transient upstream/shared-app throttling).
- **Cost:** managed-app calls count against the free tier at a lower allowance (20K of 100K tool calls/month, then
  $0.0005 each). One discovery run uses a handful.

## Setup
`SETUP.md` §4b: Composio API key → `uv run python scripts/composio_reddit_check.py` (prints a sign-in link, then
runs a real search + thread read; `--schema` prints the tool parameters).

## Verified vs not
- **Verified live (2026-11-07):** the Composio key authenticates; the managed-OAuth Reddit sign-in worked; a scoped
  search ("bands like Radiohead" in r/musicsuggestions) returned 5 relevant posts with scores; a thread read
  returned comments sorted best-first (Sigur Rós, The Smile, Mogwai, Deftones, Muse...). The parser handled the real
  response shapes. Real parameters: search takes `search_query` (required), `limit`, `sort`, `time_filter`,
  `restrict_sr`, `result_type`, `after`/`before` — **no `subreddit` parameter**, so subreddit scope is put into the
  query as `(subreddit:a OR subreddit:b) ...`; comments take `article` (required), `limit`, `sort`, `depth`.
- **Unit-tested (fake Composio client):** schema-driven argument mapping, query-based subreddit scoping, post/comment
  parsing, truncation, dedupe, caching, 429 vs other errors, missing key, tool gating on `COMPOSIO_API_KEY`.
- **NOT verified:** behaviour under heavy use (the managed app is shared, so throttling is possible and untested);
  multi-subreddit `OR` scoping against the live API (only a single-subreddit scope was run live); whether the
  supervisor's model uses the Reddit tools sensibly in a real discovery request.

## Review checklist
- Is "latest tool version" acceptable, or should it be pinned once the shape is known?
- Should Reddit be allowed when the playlist tool returned strong results, or skipped to save latency? The prompt
  currently allows up to 5 Reddit calls regardless.
- Claude Code itself still has no working Reddit MCP (`reddit-mcp-buddy` times out and its anonymous mode is likely
  blocked); Composio's MCP gateway could replace it but is not set up.
