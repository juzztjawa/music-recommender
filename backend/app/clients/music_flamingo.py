"""Music Flamingo client — audio-understanding captioning for input songs
(FR-3.2, architecture.md §4/§9).

Single endpoint contract: audio in, caption text out. The model itself is
hosted separately on serverless GPU (Modal, or RunPod Serverless as fallback
— architecture.md §9 item 3, final hosting call still pending) — this module
only talks to it over HTTP. Endpoint URL is optional/unset until that hosting
exists, following the same `*NotConfigured` pattern as every other optional
provider in `app/clients/` (FR-3.2/3.4 already require the system to degrade
gracefully when audio analysis isn't possible).
"""

import logging
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MusicFlamingoNotConfigured(RuntimeError):
    pass


async def caption_audio(audio_path: Path) -> str:
    """POST the audio file at `audio_path` to the Music Flamingo endpoint and
    return its caption text."""
    if not settings.music_flamingo_endpoint_url:
        raise MusicFlamingoNotConfigured("MUSIC_FLAMINGO_ENDPOINT_URL is not set")

    headers = {}
    if settings.music_flamingo_api_key:
        headers["Authorization"] = f"Bearer {settings.music_flamingo_api_key}"
    if settings.music_flamingo_proxy_key and settings.music_flamingo_proxy_secret:
        headers["Modal-Key"] = settings.music_flamingo_proxy_key
        headers["Modal-Secret"] = settings.music_flamingo_proxy_secret

    # The timeout must cover a serverless GPU cold start (up to ~3 min when Modal has to find a
    # free GPU) plus inference. Modal answers a web request that runs longer than ~150 s with a
    # 303 redirect to a result URL, so redirects must be followed or those requests would fail.
    upload_bytes = audio_path.stat().st_size
    started = time.perf_counter()
    async with httpx.AsyncClient(
        timeout=settings.music_flamingo_timeout_seconds, follow_redirects=True
    ) as client:
        with audio_path.open("rb") as f:
            response = await client.post(
                settings.music_flamingo_endpoint_url,
                headers=headers,
                files={"audio": (audio_path.name, f, "audio/mpeg")},
            )
    elapsed = time.perf_counter() - started
    # The endpoint reports its own GPU-side timings (decode, prefill, token counts) in the
    # X-MF-Timings header; logging it next to the round-trip time separates network from GPU.
    logger.info(
        "music_flamingo call status=%d upload_bytes=%d round_trip=%.1fs server_timings=%s",
        response.status_code,
        upload_bytes,
        elapsed,
        response.headers.get("x-mf-timings", ""),
    )
    response.raise_for_status()

    data = response.json()
    caption = data.get("caption")
    if not caption:
        raise RuntimeError(f"Music Flamingo response missing 'caption': {data!r}")
    return caption
