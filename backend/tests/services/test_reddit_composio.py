"""reddit_composio: schema-driven argument mapping, tolerant parsing, errors, caching, gating."""

import pytest

from app.clients import reddit_composio as rc
from app.tools import retrieval

SEARCH_SCHEMA = {
    "properties": {
        "search_query": {"type": "string"},
        "subreddit": {"type": "string"},
        "limit": {"type": "integer"},
        "sort": {"type": "string"},
        "t": {"type": "string"},
        "restrict_sr": {"type": "boolean"},
    },
    "required": ["search_query"],
}
COMMENTS_SCHEMA = {
    "properties": {"article": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["article"],
}


class FakeTools:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_raw_composio_tool_by_slug(self, slug):
        schema = SEARCH_SCHEMA if slug == rc.SEARCH_SLUG else COMMENTS_SCHEMA

        class T:
            input_parameters = schema

        return T()

    def execute(self, slug, **kwargs):
        self.calls.append((slug, kwargs))
        return self.response(slug) if callable(self.response) else self.response


class FakeComposio:
    def __init__(self, response):
        self.tools = FakeTools(response)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(rc, "_EMPTY_ERROR_RETRY_SECONDS", 0)
    rc._cache.clear()
    rc._schema_cache.clear()
    rc._semaphore = None
    monkeypatch.setattr(rc.settings, "composio_api_key", "k")
    monkeypatch.setattr(rc.settings, "composio_reddit_connected_account_id", "")


def install(monkeypatch, response):
    fake = FakeComposio(response)
    monkeypatch.setattr(rc, "_client", fake)
    return fake


LISTING = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc",
                    "title": "Bands like Radiohead?",
                    "subreddit": "musicsuggestions",
                    "score": 120,
                    "num_comments": 80,
                    "permalink": "/r/musicsuggestions/comments/abc/x/",
                }
            },
            {
                "data": {
                    "name": "t3_def",
                    "title": "Sad songs",
                    "subreddit": "indieheads",
                    "score": 5,
                }
            },
            {"kind": "noise", "data": {"no_title": True}},
        ]
    }
}


async def test_arguments_follow_the_tool_schema_and_posts_are_parsed(monkeypatch):
    fake = install(monkeypatch, {"successful": True, "data": LISTING})
    posts = await rc.search_reddit("bands like Radiohead", ["r/musicsuggestions"], 5)

    slug, kwargs = fake.tools.calls[0]
    assert slug == rc.SEARCH_SLUG
    args = kwargs["arguments"]
    assert (
        args["search_query"] == "bands like Radiohead" and args["subreddit"] == "musicsuggestions"
    )
    assert args["restrict_sr"] is True and args["limit"] == 5
    assert kwargs["user_id"] == rc.settings.composio_user_id
    assert kwargs["dangerously_skip_version_check"] is True
    assert [p["submission_id"] for p in posts] == ["abc", "def"]
    assert posts[0]["url"] == "https://reddit.com/r/musicsuggestions/comments/abc/x/"


async def test_second_identical_search_is_served_from_cache(monkeypatch):
    fake = install(monkeypatch, {"successful": True, "data": LISTING})
    await rc.search_reddit("x")
    await rc.search_reddit("X ")
    assert len(fake.tools.calls) == 1


async def test_comments_are_sorted_best_first_truncated_and_deduplicated(monkeypatch):
    monkeypatch.setattr(rc.settings, "reddit_max_comment_chars", 20)
    data = {
        "comments": [
            {"data": {"id": "1", "body": "low   score", "score": 1}},
            {"data": {"id": "2", "body": "Try Elbow, " + "x" * 100, "score": 50}},
            {"data": {"id": "2", "body": "duplicate", "score": 99}},
            {"data": {"id": "3", "body": "   ", "score": 10}},
        ]
    }
    install(monkeypatch, {"successful": True, "data": data})
    comments = await rc.get_thread_comments("t3_zzz", 5)
    assert [c["comment_id"] for c in comments] == ["2", "1"]
    assert len(comments[0]["body"]) == 20 and comments[1]["body"] == "low score"


async def test_rate_limit_and_tool_errors_are_distinguished(monkeypatch):
    install(monkeypatch, {"successful": False, "error": "429 Too Many Requests"})
    with pytest.raises(rc.RedditRateLimited):
        await rc.search_reddit("a")
    install(monkeypatch, {"successful": False, "error": "No active connection for reddit"})
    with pytest.raises(rc.RedditError, match="No active connection"):
        await rc.search_reddit("b")


async def test_unmappable_required_parameter_names_it(monkeypatch):
    install(monkeypatch, {"successful": True, "data": {}})
    rc._schema_cache[rc.SEARCH_SLUG] = {"properties": {"weird": {}}, "required": ["weird"]}
    with pytest.raises(rc.RedditError, match="weird"):
        await rc.search_reddit("c")


async def test_not_configured_without_api_key(monkeypatch):
    monkeypatch.setattr(rc, "_client", None)
    monkeypatch.setattr(rc.settings, "composio_api_key", "")
    with pytest.raises(rc.RedditNotConfigured):
        await rc.search_reddit("d")


def test_reddit_tools_are_offered_only_with_a_composio_key(monkeypatch):
    names = lambda: {t.name for t in retrieval.available_tools()}  # noqa: E731
    monkeypatch.setattr(retrieval.settings, "composio_api_key", "")
    assert "search_reddit_tool" not in names()
    monkeypatch.setattr(retrieval.settings, "composio_api_key", "k")
    assert {"search_reddit_tool", "read_reddit_thread_tool"} <= names()


async def test_subreddit_scope_goes_into_the_query_when_the_tool_has_no_subreddit_parameter(
    monkeypatch,
):
    fake = install(monkeypatch, {"successful": True, "data": {}})
    rc._schema_cache[rc.SEARCH_SLUG] = {
        "properties": {
            "search_query": {},
            "restrict_sr": {},
            "limit": {},
            "sort": {},
            "time_filter": {},
        },
        "required": ["search_query"],
    }
    await rc.search_reddit("bands like Radiohead", ["musicsuggestions", "indieheads"], 5)
    args = fake.tools.calls[0][1]["arguments"]
    assert (
        args["search_query"]
        == "(subreddit:musicsuggestions OR subreddit:indieheads) bands like Radiohead"
    )
    assert "restrict_sr" not in args and args["time_filter"] == "all"


async def test_empty_error_failure_is_retried_once_then_succeeds(monkeypatch):
    results = iter([{"successful": False, "error": None}, {"successful": True, "data": LISTING}])
    fake = install(monkeypatch, lambda slug: next(results))
    posts = await rc.search_reddit("flaky")
    assert len(fake.tools.calls) == 2 and posts


async def test_persistent_empty_error_reports_the_raw_response_not_unknown_error(monkeypatch):
    fake = install(monkeypatch, {"successful": False, "error": "", "log_id": "log_123"})
    with pytest.raises(rc.RedditError, match="log_123"):
        await rc.search_reddit("always broken")
    assert len(fake.tools.calls) == 2  # one retry, no loop
