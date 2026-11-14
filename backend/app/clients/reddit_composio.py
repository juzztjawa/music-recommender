"""Reddit client via Composio's managed OAuth app (docs/10-reddit-composio.md).

Replaces the shelved PRAW client (backend/archive/reddit/): Reddit requires its own
developer credentials, which we cannot get, whereas Composio holds a managed OAuth
app and we only sign in with a normal Reddit account (`scripts/composio_reddit_check.py`).

Two tools are used: REDDIT_SEARCH_ACROSS_SUBREDDITS and REDDIT_RETRIEVE_POST_COMMENTS.
Their parameter names could not be read without an API key, so instead of hard-coding
guesses `_build_arguments` reads the tool's published input schema (once, cached) and
maps our canonical fields onto whichever of the candidate names exist. If a *required*
parameter cannot be mapped the call fails with a message naming it, which is the cue to
run the check script and extend `_ALIASES`. Output parsing is equally defensive.

Reddit rate limits are per OAuth app/account and Composio's managed app is shared, so
this module caps concurrency, caches (searches 1 h, threads 6 h) and surfaces a throttle
as `RedditRateLimited` rather than retrying in a loop. The Composio SDK is synchronous,
so calls run in a thread bounded by `provider_call_timeout_seconds`.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_EMPTY_ERROR_RETRY_SECONDS = 2.0

SEARCH_SLUG = "REDDIT_SEARCH_ACROSS_SUBREDDITS"
COMMENTS_SLUG = "REDDIT_RETRIEVE_POST_COMMENTS"
SEARCH_TTL_SECONDS = 3600
THREAD_TTL_SECONDS = 6 * 3600

# canonical field -> candidate parameter names, in preference order
_ALIASES: dict[str, list[str]] = {
    "query": ["query", "q", "search_query", "search", "search_term", "keywords"],
    "subreddit": ["subreddit", "subreddit_name", "subreddits", "sr", "subreddit_names"],
    "limit": ["limit", "count", "max_results", "per_page", "size"],
    "sort": ["sort", "sort_by", "order"],
    "time": ["t", "time", "time_filter", "timeframe", "time_range"],
    "post_id": ["article", "article_id", "post_id", "submission_id", "id", "post", "link_id"],
    "restrict": ["restrict_sr", "restrict_to_subreddit"],
}

_client: Any = None
_semaphore: asyncio.Semaphore | None = None
_schema_cache: dict[str, dict] = {}
_cache: dict[tuple, tuple[float, Any]] = {}


class RedditNotConfigured(RuntimeError):
    pass


class RedditRateLimited(RuntimeError):
    pass


class RedditError(RuntimeError):
    pass


def _get_client() -> Any:
    global _client
    if _client is None:
        if not settings.composio_api_key:
            raise RedditNotConfigured("COMPOSIO_API_KEY is not set")
        from composio import Composio  # local import: keep SDK import cost off other paths

        _client = Composio(api_key=settings.composio_api_key)
    return _client


def _gate() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(2)
    return _semaphore


def _cache_get(key: tuple) -> Any | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    _cache.pop(key, None)
    return None


def _input_schema(slug: str) -> dict:
    if slug not in _schema_cache:
        tool = _get_client().tools.get_raw_composio_tool_by_slug(slug)
        _schema_cache[slug] = dict(getattr(tool, "input_parameters", None) or {})
    return _schema_cache[slug]


def _build_arguments(slug: str, values: dict[str, Any]) -> dict[str, Any]:
    """Map canonical field names to this tool's real parameter names via its schema."""
    schema = _input_schema(slug)
    props: dict = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    args: dict[str, Any] = {}
    mapped: set[str] = set()
    values = dict(values)
    # REDDIT_SEARCH_ACROSS_SUBREDDITS has no subreddit parameter (live schema, 2026-11-07):
    # scope with Reddit's own search syntax instead, and don't send restrict_sr either.
    if values.get("subreddit") and not any(a in props for a in _ALIASES["subreddit"]):
        subs = values.pop("subreddit")
        subs = subs if isinstance(subs, list) else [subs]
        scope = " OR ".join(f"subreddit:{s}" for s in subs)
        values["query"] = (
            f"({scope}) {values['query']}" if len(subs) > 1 else f"{scope} {values['query']}"
        )
        values.pop("restrict", None)
    for field, value in values.items():
        if value is None:
            continue
        name = next((a for a in _ALIASES[field] if a in props), None)
        if name is None:
            continue
        # a list-typed parameter wants a list, a string one wants a string
        if field == "subreddit" and isinstance(value, list):
            value = value if props[name].get("type") == "array" else "+".join(value)
        args[name] = value
        mapped.add(name)
    missing = [r for r in required if r not in mapped]
    if missing:
        raise RedditError(
            f"{slug}: required parameter(s) {missing} not understood; schema has "
            f"{sorted(props)}. Run scripts/composio_reddit_check.py and extend _ALIASES."
        )
    return args


def _raw(result: Any) -> str:
    """Compact, bounded dump of a Composio response for logs and error messages."""
    try:
        return json.dumps(result, default=str)[:600]
    except Exception:  # noqa: BLE001
        return repr(result)[:600]


def _execute(slug: str, values: dict[str, Any]) -> Any:
    client = _get_client()
    kwargs: dict[str, Any] = {
        "arguments": _build_arguments(slug, values),
        "user_id": settings.composio_user_id,
        # LLM + tolerant parsing consume the output, so latest is acceptable (see docs/10)
        "dangerously_skip_version_check": True,
    }
    if settings.composio_reddit_connected_account_id:
        kwargs["connected_account_id"] = settings.composio_reddit_connected_account_id
    for attempt in (1, 2):
        result = client.tools.execute(slug, **kwargs)
        if result.get("successful", False):
            break
        error = str(result.get("error") or "").strip()
        # Composio sometimes reports an upstream (Reddit/shared-app) hiccup as a failure with
        # no message (seen live 2026-11-07, run f1636530: two calls, 10 s and 5 s, "unknown
        # error", while the identical calls succeeded minutes later). Retry that once.
        if not error and attempt == 1:
            logger.warning(
                "%s failed with an empty error; retrying once. raw=%s", slug, _raw(result)
            )
            time.sleep(_EMPTY_ERROR_RETRY_SECONDS)
            continue
        logger.warning("%s failed: raw=%s", slug, _raw(result))
        detail = error or f"no error message from Composio; raw response: {_raw(result)}"
        if "429" in detail or "rate limit" in detail.lower() or "too many" in detail.lower():
            raise RedditRateLimited(detail[:300])
        raise RedditError(f"{slug}: {detail[:400]}")
    return result.get("data")


def _walk(obj: Any):
    """Yield every dict nested anywhere in `obj` (tool outputs wrap listings differently)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _post_from(d: dict) -> dict | None:
    d = d.get("data") if isinstance(d.get("data"), dict) and "title" in d["data"] else d
    if not d.get("title") or not (d.get("id") or d.get("name")):
        return None
    post_id = str(d.get("id") or str(d["name"]).removeprefix("t3_"))
    permalink = d.get("permalink") or ""
    return {
        "source": "reddit",
        "submission_id": post_id,
        "title": str(d["title"]),
        "subreddit": str(d.get("subreddit") or ""),
        "score": d.get("score"),
        "num_comments": d.get("num_comments"),
        "url": f"https://reddit.com{permalink}" if permalink.startswith("/") else d.get("url"),
        "snippet": str(d.get("selftext") or "")[: settings.reddit_max_comment_chars],
    }


def parse_posts(data: Any, limit: int) -> list[dict]:
    seen: set[str] = set()
    posts: list[dict] = []
    for d in _walk(data):
        post = _post_from(d)
        if post and post["submission_id"] not in seen:
            seen.add(post["submission_id"])
            posts.append(post)
    return posts[:limit]


def parse_comments(data: Any, limit: int) -> list[dict]:
    """Comments sorted best-first, bodies truncated; reddit text is untrusted user content."""
    comments: list[dict] = []
    seen: set[str] = set()
    for d in _walk(data):
        d = d["data"] if isinstance(d.get("data"), dict) and "body" in d["data"] else d
        body = d.get("body")
        cid = str(d.get("id") or d.get("name") or "")
        if not isinstance(body, str) or not body.strip() or (cid and cid in seen):
            continue
        seen.add(cid)
        body = re.sub(r"\s+", " ", body).strip()
        comments.append(
            {
                "source": "reddit",
                "comment_id": cid or None,
                "score": d.get("score") if isinstance(d.get("score"), int | float) else 0,
                "body": body[: settings.reddit_max_comment_chars],
            }
        )
    comments.sort(key=lambda c: c["score"], reverse=True)
    return comments[:limit]


async def _run(slug: str, values: dict[str, Any]) -> Any:
    async with _gate():
        return await asyncio.wait_for(
            asyncio.to_thread(_execute, slug, values),
            timeout=settings.provider_call_timeout_seconds,
        )


async def search_reddit(
    query: str, subreddits: list[str] | None = None, limit: int = 15
) -> list[dict]:
    """Search Reddit posts for `query`, optionally within a subreddit allowlist."""
    subs = [s.strip().removeprefix("r/") for s in (subreddits or []) if s.strip()]
    key = ("search", query.strip().lower(), tuple(sorted(subs)), limit)
    if (cached := _cache_get(key)) is not None:
        return cached
    data = await _run(
        SEARCH_SLUG,
        {
            "query": query,
            "subreddit": subs or None,
            "restrict": bool(subs) or None,
            "limit": limit,
            "sort": "relevance",
            "time": "all",
        },
    )
    posts = parse_posts(data, limit)
    _cache[key] = (time.monotonic() + SEARCH_TTL_SECONDS, posts)
    return posts


async def get_thread_comments(post_id: str, limit: int = 25) -> list[dict]:
    """Top comments of one post (id as returned by `search_reddit`'s `submission_id`)."""
    post_id = post_id.removeprefix("t3_")
    key = ("thread", post_id, limit)
    if (cached := _cache_get(key)) is not None:
        return cached
    data = await _run(COMMENTS_SLUG, {"post_id": post_id, "limit": limit * 2, "sort": "top"})
    comments = parse_comments(data, limit)
    _cache[key] = (time.monotonic() + THREAD_TTL_SECONDS, comments)
    return comments
