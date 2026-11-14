"""Connect Reddit through Composio and smoke-test the two tools the backend uses.

    uv run python scripts/composio_reddit_check.py           # connect (if needed) + smoke test
    uv run python scripts/composio_reddit_check.py --schema  # also print the tools' schemas

Needs COMPOSIO_API_KEY in backend/.env. Opens no Reddit developer app: Composio's managed
OAuth app shows a consent page where you sign in with an ordinary Reddit account.
Prints the connected account id — put it in COMPOSIO_REDDIT_CONNECTED_ACCOUNT_ID only if you
have several Reddit logins under the same COMPOSIO_USER_ID.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients import reddit_composio as rc
from app.config import settings


def connect() -> None:
    client = rc._get_client()
    session = client.create(user_id=settings.composio_user_id, toolkits=["reddit"])
    items = session.toolkits().items
    reddit = next((t for t in items if t.slug == "reddit"), None)
    if reddit and reddit.connection and reddit.connection.is_active:
        print(f"Reddit already connected: {reddit.connection.connected_account.id}")
        return
    request = session.authorize("reddit")
    print("Open this link, sign in to Reddit and approve:\n  ", request.redirect_url)
    account = request.wait_for_connection(300)
    print(f"Connected. connected_account_id={account.id}")


async def smoke() -> None:
    posts = await rc.search_reddit("bands like Radiohead", ["musicsuggestions"], 5)
    print(f"search -> {len(posts)} posts")
    for p in posts[:5]:
        print(f"  [{p['score']}] r/{p['subreddit']} {p['title'][:80]}  ({p['submission_id']})")
    if posts:
        comments = await rc.get_thread_comments(posts[0]["submission_id"], 5)
        print(f"thread {posts[0]['submission_id']} -> {len(comments)} comments")
        for c in comments:
            print(f"  [{c['score']}] {c['body'][:100]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", action="store_true", help="print the tools' input schemas")
    args = parser.parse_args()
    connect()
    if args.schema:
        for slug in (rc.SEARCH_SLUG, rc.COMMENTS_SLUG):
            print(slug, json.dumps(rc._input_schema(slug), indent=2)[:3000])
    asyncio.run(smoke())


if __name__ == "__main__":
    main()
