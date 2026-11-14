"""Audio Analysis Agent (architecture.md §2/§3, FR-3.2/3.4).

Small and deterministic despite the "agent" name in the design — no LLM
reasoning happens here, unlike the Retrieval & Evidence Agent. Kept as its
own module/boundary because the audio-model backend or download approach is
the most likely piece to get swapped later (architecture.md §2): resolve an
input song -> yt-dlp download -> Music Flamingo caption call -> discard audio.

FR-3.2/3.4 scope this as best-effort and input-song-only (never run against
retrieval candidates). If any step fails - download, or the captioning
backend being unreachable/not yet deployed - the result carries `error`
instead of `caption`. This function must never raise: the caller continues
the recommendation flow without a caption rather than failing the whole
request (FR-3.2's graceful-degradation requirement).
"""

import logging
import tempfile
import time
from pathlib import Path

from app.clients.music_flamingo import caption_audio
from app.clients.youtube_audio import download_audio
from app.config import settings
from app.schemas.audio import AudioAnalysisResult

logger = logging.getLogger(__name__)


async def analyze_input_song(query: str) -> AudioAnalysisResult:
    """Resolve `query` (e.g. "Bohemian Rhapsody Queen") to YouTube audio,
    caption it, and discard the audio before returning.

    Logs how long each step took (download, caption call, total) so a slow song can be traced
    to its step; the caption call logs its own network/GPU split (see the client)."""
    # Without a captioning backend a download would be pure waste (~10 s and a
    # YouTube request per song) — the audio can't be analysed either way.
    if not settings.music_flamingo_endpoint_url:
        return AudioAnalysisResult(
            query=query, error="audio analysis is not configured on this server"
        )
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="orchestra-audio-") as tmp:
        try:
            downloaded = await download_audio(query, Path(tmp))
        except Exception as e:
            logger.warning(
                "Audio download failed for %r after %.1fs: %s", query, _since(started), e
            )
            return AudioAnalysisResult(query=query, error=f"download failed: {e}")
        download_s = _since(started)
        logger.info(
            "audio download ok query=%r title=%r source=%s bytes=%d took=%.1fs",
            query,
            downloaded.title,
            downloaded.source_url,
            downloaded.path.stat().st_size,
            download_s,
        )

        try:
            caption = await caption_audio(downloaded.path)
        except Exception as e:
            logger.warning(
                "Audio captioning failed for %r after %.1fs: %s", query, _since(started), e
            )
            return AudioAnalysisResult(
                query=query, source_url=downloaded.source_url, error=f"captioning failed: {e}"
            )

    logger.info(
        "audio analysis done query=%r download=%.1fs caption=%.1fs total=%.1fs caption_words=%d",
        query,
        download_s,
        _since(started) - download_s,
        _since(started),
        len(caption.split()),
    )
    return AudioAnalysisResult(query=query, caption=caption, source_url=downloaded.source_url)


def _since(started: float) -> float:
    """Seconds elapsed since a `time.perf_counter()` reading."""
    return time.perf_counter() - started
