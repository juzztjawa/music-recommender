"""YouTube Data API client — candidate tracks + community signal (FR-6).

Plain REST via httpx, no official async SDK for the Data API.
"""

import httpx

from app.config import settings

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeNotConfigured(RuntimeError):
    pass


async def search_youtube(query: str, limit: int = 10) -> list[dict]:
    """Search YouTube for candidates and their view/comment community signal."""
    if not settings.youtube_api_key:
        raise YouTubeNotConfigured("YOUTUBE_API_KEY is not set")

    async with httpx.AsyncClient(timeout=10.0) as client:
        search_resp = await client.get(
            _SEARCH_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "videoCategoryId": "10",  # Music
                "maxResults": limit,
                "key": settings.youtube_api_key,
            },
        )
        search_resp.raise_for_status()
        items = search_resp.json().get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]

        stats_by_id: dict[str, dict] = {}
        if video_ids:
            stats_resp = await client.get(
                _VIDEOS_URL,
                params={
                    "part": "statistics",
                    "id": ",".join(video_ids),
                    "key": settings.youtube_api_key,
                },
            )
            stats_resp.raise_for_status()
            for video in stats_resp.json().get("items", []):
                stats_by_id[video["id"]] = video.get("statistics", {})

    candidates = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        stats = stats_by_id.get(video_id, {})
        candidates.append(
            {
                "source": "youtube",
                "video_id": video_id,
                "title": snippet.get("title"),
                "channel": snippet.get("channelTitle"),
                "published_at": snippet.get("publishedAt"),
                "view_count": stats.get("viewCount"),
                "like_count": stats.get("likeCount"),
                "comment_count": stats.get("commentCount"),
            }
        )
    return candidates
