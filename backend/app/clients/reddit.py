"""Reddit client — community discussion evidence (FR-6).

Client ID + secret + User-Agent alone puts PRAW in read-only (app-only) mode,
which is all search needs — no user login required. `praw` is synchronous,
so calls run in a thread.
"""

import asyncio

import praw

from app.config import settings

_client: praw.Reddit | None = None


class RedditNotConfigured(RuntimeError):
    pass


def _get_client() -> praw.Reddit:
    global _client
    if _client is None:
        if not (settings.reddit_client_id and settings.reddit_client_secret):
            raise RedditNotConfigured("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET are not set")
        _client = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
    return _client


def _search_sync(query: str, subreddits: list[str] | None, limit: int) -> list[dict]:
    client = _get_client()
    scope = "+".join(subreddits) if subreddits else "all"
    submissions = client.subreddit(scope).search(query, limit=limit)
    return [
        {
            "source": "reddit",
            "submission_id": submission.id,
            "title": submission.title,
            "subreddit": str(submission.subreddit),
            "score": submission.score,
            "num_comments": submission.num_comments,
            "url": f"https://reddit.com{submission.permalink}",
        }
        for submission in submissions
    ]


async def search_reddit(
    query: str, subreddits: list[str] | None = None, limit: int = 15
) -> list[dict]:
    """Search Reddit for discussion/curation evidence matching `query`."""
    return await asyncio.to_thread(_search_sync, query, subreddits, limit)
