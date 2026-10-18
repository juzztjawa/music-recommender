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
from pathlib import Path

from pydantic import BaseModel

from app.clients.music_flamingo import caption_audio
from app.clients.youtube_audio import download_audio

logger = logging.getLogger(__name__)


class AudioAnalysisResult(BaseModel):
    query: str
    caption: str | None = None
    source_url: str | None = None
    error: str | None = None


async def analyze_input_song(query: str) -> AudioAnalysisResult:
    """Resolve `query` (e.g. "Bohemian Rhapsody Queen") to YouTube audio,
    caption it, and discard the audio before returning."""
    with tempfile.TemporaryDirectory(prefix="orchestra-audio-") as tmp:
        try:
            downloaded = await download_audio(query, Path(tmp))
        except Exception as e:
            logger.warning("Audio download failed for %r: %s", query, e)
            return AudioAnalysisResult(query=query, error=f"download failed: {e}")

        try:
            caption = await caption_audio(downloaded.path)
        except Exception as e:
            logger.warning("Audio captioning failed for %r: %s", query, e)
            return AudioAnalysisResult(
                query=query, source_url=downloaded.source_url, error=f"captioning failed: {e}"
            )

    return AudioAnalysisResult(query=query, caption=caption, source_url=downloaded.source_url)
