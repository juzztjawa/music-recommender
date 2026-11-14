# Reddit provider via PRAW — shelved (2026-11-01)

> **Superseded 2026-11-07:** Reddit is back through Composio's managed OAuth app, which needs no Reddit
> developer credentials — see `docs/10-reddit-composio.md`. This PRAW client is kept only for the case
> where you get your own Reddit API credentials and want to skip Composio.

Removed from the retrieval agent because the Reddit developer account was suspended and the
appeal is a dead end; the client (PRAW, app-only) needs `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`.

Findings when it was shelved (from this machine): anonymous `.json` endpoints return 403;
RSS (`/r/<sub>/search.rss`, `/r/<sub>/.rss`) returns 200 but 429s after ~4 quick requests.

## To bring it back (if you get credentials)
1. `git mv backend/archive/reddit/client.py backend/app/clients/reddit.py`
2. Copy `tool.py`'s `search_reddit_tool` into `app/tools/retrieval.py`, and in `available_tools()` add
   `if settings.reddit_client_id and settings.reddit_client_secret: tools.append(search_reddit_tool)`
3. Add to `app/config.py` `Settings`: `reddit_client_id`, `reddit_client_secret: str = ""`,
   `reddit_user_agent: str = "orchestra-recommender/0.1"`; add the `REDDIT_*` lines to `.env.example`.
4. `uv add praw`
5. Add "Reddit" back to the `retrieve_candidates` docstring in `app/tools/orchestrator.py` and to
   `retrieval-agent-tool-schemas.json`.
