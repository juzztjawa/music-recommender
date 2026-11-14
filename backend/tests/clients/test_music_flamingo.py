"""Wire-contract tests for app.clients.music_flamingo against a mocked HTTP endpoint.

These pin what the Modal endpoint (modal_app/api.py) relies on: multipart field `audio`,
`Authorization: Bearer <key>`, and a 200 body of {"caption": "..."}. The real endpoint is
exercised by modal_app/tests/test_live_endpoint.py and by the end-to-end run in SETUP.md.
"""

import functools

import httpx
import pytest

from app.clients import music_flamingo
from app.clients.music_flamingo import MusicFlamingoNotConfigured, caption_audio


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "song.mp3"
    p.write_bytes(b"ID3fake-mp3-bytes")
    return p


@pytest.fixture
def configure(monkeypatch):
    monkeypatch.setattr(
        music_flamingo.settings, "music_flamingo_endpoint_url", "http://captioner.test/"
    )
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_api_key", "secret-key")


def mock_endpoint(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        music_flamingo.httpx,
        "AsyncClient",
        functools.partial(httpx.AsyncClient, transport=transport),
    )


async def test_posts_multipart_audio_with_bearer_and_returns_caption(
    monkeypatch, configure, audio_file
):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["ctype"] = request.headers.get("content-type", "")
        seen["body"] = request.read()
        return httpx.Response(200, json={"caption": "a calm piano ballad"})

    mock_endpoint(monkeypatch, handler)
    assert await caption_audio(audio_file) == "a calm piano ballad"
    assert seen["auth"] == "Bearer secret-key"
    assert seen["ctype"].startswith("multipart/form-data")
    assert b'name="audio"' in seen["body"] and b"ID3fake-mp3-bytes" in seen["body"]


async def test_no_auth_header_when_key_unset(monkeypatch, configure, audio_file):
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_api_key", "")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"caption": "x"})

    mock_endpoint(monkeypatch, handler)
    await caption_audio(audio_file)
    assert seen["auth"] is None


@pytest.mark.parametrize("status", [401, 422, 502])
async def test_error_statuses_raise(monkeypatch, configure, audio_file, status):
    mock_endpoint(monkeypatch, lambda request: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(httpx.HTTPStatusError):
        await caption_audio(audio_file)


@pytest.mark.parametrize("body", [{}, {"caption": ""}, {"caption": None}])
async def test_missing_or_empty_caption_raises(monkeypatch, configure, audio_file, body):
    mock_endpoint(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(RuntimeError, match="missing 'caption'"):
        await caption_audio(audio_file)


async def test_unconfigured_raises(monkeypatch, audio_file):
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_endpoint_url", "")
    with pytest.raises(MusicFlamingoNotConfigured):
        await caption_audio(audio_file)


async def test_timeout_propagates(monkeypatch, configure, audio_file):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    mock_endpoint(monkeypatch, handler)
    with pytest.raises(httpx.ReadTimeout):
        await caption_audio(audio_file)


async def test_follows_modal_303_redirect_to_the_result(monkeypatch, configure, audio_file):
    """Modal answers a request outliving ~150 s with a 303 to a URL that returns the result."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(303, headers={"location": "http://captioner.test/__result"})
        return httpx.Response(200, json={"caption": "a slow but finished caption"})

    mock_endpoint(monkeypatch, handler)
    assert await caption_audio(audio_file) == "a slow but finished caption"


async def test_proxy_token_headers_sent_when_configured(monkeypatch, configure, audio_file):
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_proxy_key", "wk-test")
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_proxy_secret", "ws-test")
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("modal-key")
        seen["secret"] = request.headers.get("modal-secret")
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"caption": "x"})

    mock_endpoint(monkeypatch, handler)
    await caption_audio(audio_file)
    assert (seen["key"], seen["secret"]) == ("wk-test", "ws-test")
    assert seen["auth"] == "Bearer secret-key"  # the in-container bearer check still gets its token


async def test_no_proxy_headers_when_not_configured(monkeypatch, configure, audio_file):
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_proxy_key", "")
    monkeypatch.setattr(music_flamingo.settings, "music_flamingo_proxy_secret", "")
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("modal-key")
        return httpx.Response(200, json={"caption": "x"})

    mock_endpoint(monkeypatch, handler)
    await caption_audio(audio_file)
    assert seen["key"] is None
