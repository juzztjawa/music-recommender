"""YouTube audio acquisition via yt-dlp (architecture.md §4/§9, FR-3.2).

Resolves a free-text song query to a YouTube video via yt-dlp's own search
(no YouTube Data API key needed — this is independent of `app/clients/youtube.py`),
downloads its audio track, and extracts it to mp3. `yt-dlp` is synchronous, so
calls run in a thread, same pattern as the other sync provider SDKs.

Process-and-discard per architecture.md §17: the caller owns cleanup of
`dest_dir`, this module never persists anything itself.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

# A single track shouldn't run long; this guards against yt-dlp's search
# matching a full album/live-set/mix instead of the intended song, before
# spending time downloading and transcoding it.
_MAX_DURATION_SECONDS = 15 * 60


class YoutubeAudioDownloadError(RuntimeError):
    pass


@dataclass
class DownloadedAudio:
    path: Path
    source_url: str | None
    title: str | None


def _download_sync(query: str, dest_dir: Path) -> DownloadedAudio:
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # YouTube now requires a PO (proof-of-origin) token for most formats
        # on the default web client, which yt-dlp can't obtain without a
        # browser-derived token/cookies — surfaces as a live 403 on download
        # (confirmed live). The android client still serves formats that
        # don't require one; `formats: missing_pot` explicitly allows using
        # them instead of erroring out.
        "extractor_args": {"youtube": {"player_client": ["android"], "formats": ["missing_pot"]}},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        search_info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (search_info or {}).get("entries") or []
        if not entries:
            raise YoutubeAudioDownloadError(f"No results for query: {query!r}")

        entry = entries[0]
        duration = entry.get("duration")
        if duration and duration > _MAX_DURATION_SECONDS:
            raise YoutubeAudioDownloadError(
                f"Top result for {query!r} is {duration}s, exceeds the "
                f"{_MAX_DURATION_SECONDS}s cap (likely not a single track)"
            )

        video_url = entry.get("webpage_url") or entry["url"]
        result = ydl.extract_info(video_url, download=True)

        requested = (result or {}).get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            audio_path = Path(requested[0]["filepath"])
        else:
            audio_path = Path(ydl.prepare_filename(result)).with_suffix(".mp3")

        if not audio_path.exists():
            raise YoutubeAudioDownloadError(f"Expected audio file not found: {audio_path}")

        return DownloadedAudio(
            path=audio_path,
            source_url=result.get("webpage_url"),
            title=result.get("title"),
        )


async def download_audio(query: str, dest_dir: Path) -> DownloadedAudio:
    """Resolve `query` to a YouTube video and download its audio as mp3 into
    `dest_dir`. Raises `YoutubeAudioDownloadError` on no match or a bad match."""
    return await asyncio.to_thread(_download_sync, query, dest_dir)
