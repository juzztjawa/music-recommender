"""Archived LangChain tool wrapper for the Reddit provider (not imported anywhere).

Paste back into `app/tools/retrieval.py` to re-enable; see README.md in this folder.
"""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.clients.reddit import search_reddit


@tool
async def search_reddit_tool(
    query: Annotated[str, Field(min_length=1, max_length=300, description="Search text")],
    subreddits: Annotated[
        list[str] | None, Field(description="Optional subreddit allowlist to scope the search")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=30, description="Max results")] = 15,
) -> list[dict]:
    """Search Reddit for community discussion evidence: threads and curated playlist mentions."""
    return await search_reddit(query, subreddits, limit)
