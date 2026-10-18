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

from pathlib import Path

import httpx

from app.config import settings


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

    # Generous timeout: serverless GPU cold starts run ~20-45s per
    # architecture.md §9, on top of the actual inference call.
    async with httpx.AsyncClient(timeout=settings.music_flamingo_timeout_seconds) as client:
        with audio_path.open("rb") as f:
            response = await client.post(
                settings.music_flamingo_endpoint_url,
                headers=headers,
                files={"audio": (audio_path.name, f, "audio/mpeg")},
            )
    response.raise_for_status()

    data = response.json()
    caption = data.get("caption")
    if not caption:
        raise RuntimeError(f"Music Flamingo response missing 'caption': {data!r}")
    return caption
