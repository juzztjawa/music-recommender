"""HTTP-contract tests that run locally with a fake engine (no GPU, no Modal, no network)."""

import io

import httpx
import numpy as np
import pytest
import soundfile as sf

from flamingo.api import create_app
from flamingo.common import CaptionResult, clean_caption

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeEngine:
    def __init__(self, text="A warm, mid-tempo track. It builds slowly.", fail=False):
        self.text, self.fail, self.calls = text, fail, 0

    async def caption(self, path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return CaptionResult(self.text, {"engine_s": 0.01})

    def info(self):
        return {"engine": "fake"}


def wav_bytes(seconds=1.0):
    buf = io.BytesIO()
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    sf.write(buf, 0.1 * np.sin(2 * np.pi * 440 * t), 16000, format="WAV")
    return buf.getvalue()


def client(engine=None, **kw):
    engine = engine or FakeEngine()
    app = create_app(engine, TOKEN, **kw)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t"), engine


async def post(c, data, headers=AUTH, name="a.wav"):
    return await c.post("/", headers=headers, files={"audio": (name, data, "audio/wav")})


async def test_ok_returns_caption_and_timing_header():
    c, engine = client()
    r = await post(c, wav_bytes())
    assert r.status_code == 200
    assert r.json() == {"caption": "A warm, mid-tempo track. It builds slowly."}
    assert "api_total_s" in r.headers["x-mf-timings"]
    assert engine.calls == 1


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}]
)
async def test_bad_or_missing_token_is_401_and_engine_not_called(headers):
    c, engine = client()
    r = await post(c, wav_bytes(), headers=headers)
    assert r.status_code == 401
    assert engine.calls == 0


async def test_empty_upload_is_422():
    c, _ = client()
    assert (await post(c, b"")).status_code == 422


async def test_undecodable_audio_is_422_and_engine_not_called():
    c, engine = client()
    r = await post(c, b"this is definitely not audio" * 100)
    assert r.status_code == 422
    assert engine.calls == 0


async def test_oversize_upload_is_413():
    c, _ = client(max_upload_bytes=1000)
    assert (await post(c, wav_bytes(1.0))).status_code == 413


async def test_engine_exception_is_502_without_leaking_detail():
    c, _ = client(FakeEngine(fail=True))
    r = await post(c, wav_bytes())
    assert r.status_code == 502
    assert "boom" not in r.text


async def test_empty_caption_is_502():
    c, _ = client(FakeEngine(text="  **  "))
    assert (await post(c, wav_bytes())).status_code == 502


async def test_missing_audio_field_is_422():
    c, _ = client()
    r = await c.post("/", headers=AUTH, files={"other": ("a.wav", wav_bytes(), "audio/wav")})
    assert r.status_code == 422


async def test_stats_requires_auth_and_reports_engine():
    c, _ = client()
    assert (await c.get("/stats")).status_code == 401
    body = (await c.get("/stats", headers=AUTH)).json()
    assert body["engine"] == "fake"
    assert body["requests"]["served"] == 0


async def test_healthz_is_open():
    c, _ = client()
    assert (await c.get("/healthz")).json() == {"ok": True}


def test_clean_caption_strips_markdown_and_trims_truncation():
    assert clean_caption("**Genre:** pop\n\n# Mood\nCalm.") == "Genre: pop Mood Calm."
    assert (
        clean_caption("It starts soft. Then it builds and the drums come in with")
        == "It starts soft."
    )
