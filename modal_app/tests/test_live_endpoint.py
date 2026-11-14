"""Contract test against the REAL deployed endpoint. Skipped unless both env vars are set:

    MUSIC_FLAMINGO_ENDPOINT_URL=https://...modal.run MUSIC_FLAMINGO_API_KEY=... \
        uv run pytest -m live

Costs GPU seconds (a cold start if the app is scaled to zero). Used as the post-deploy smoke
test in CI.
"""

import io
import os

import httpx
import numpy as np
import pytest
import soundfile as sf

URL = os.environ.get("MUSIC_FLAMINGO_ENDPOINT_URL", "")
KEY = os.environ.get("MUSIC_FLAMINGO_API_KEY", "")
# Modal proxy token: required once the endpoint has requires_proxy_auth=True.
PROXY = (
    {
        "Modal-Key": os.environ["MUSIC_FLAMINGO_PROXY_KEY"],
        "Modal-Secret": os.environ["MUSIC_FLAMINGO_PROXY_SECRET"],
    }
    if os.environ.get("MUSIC_FLAMINGO_PROXY_KEY") and os.environ.get("MUSIC_FLAMINGO_PROXY_SECRET")
    else {}
)
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (URL and KEY), reason="set MUSIC_FLAMINGO_ENDPOINT_URL and MUSIC_FLAMINGO_API_KEY"
    ),
]


def tone(seconds=8.0):
    buf = io.BytesIO()
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    sf.write(
        buf,
        0.2 * np.sin(2 * np.pi * 220 * t) * (1 + np.sin(2 * np.pi * 2 * t)),
        16000,
        format="WAV",
    )
    return buf.getvalue()


def post(data, key=KEY, proxy=True):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if proxy:
        headers.update(PROXY)
    return httpx.post(
        URL, headers=headers, files={"audio": ("t.wav", data, "audio/wav")}, timeout=300
    )


def test_wrong_token_401():
    assert post(tone(), key="wrong").status_code == 401


@pytest.mark.skipif(not PROXY, reason="endpoint has no proxy token configured")
def test_missing_proxy_token_is_rejected_at_the_edge():
    assert post(b"x", proxy=False).status_code == 401


def test_garbage_is_4xx():
    assert 400 <= post(b"not audio" * 50).status_code < 500


def test_caption_shape_and_length():
    r = post(tone())
    assert r.status_code == 200
    caption = r.json()["caption"]
    assert isinstance(caption, str) and len(caption.split()) > 20
    assert "*" not in caption and "#" not in caption  # prose only
