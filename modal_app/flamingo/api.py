"""HTTP layer for the captioning endpoint. Knows nothing about Modal or GPUs, so it is
unit-tested locally with a fake engine (tests/test_api.py).

Contract (set by backend/app/clients/music_flamingo.py):
  POST /  multipart field `audio` + `Authorization: Bearer <token>`
      -> 200 {"caption": "..."}   401 bad/missing token   413 too big
         422 empty/undecodable   502 engine failure
  GET /stats    (auth) engine config, startup timings, GPU memory, request counters
  GET /healthz  (no auth) liveness only
Per-request timings go back in the `X-MF-Timings` response header (JSON), never in the body.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import subprocess
import tempfile
import threading
import time

import librosa
from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from flamingo.common import SAMPLE_RATE, clean_caption

log = logging.getLogger("music-flamingo")

MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # backend caps at ~20 MB; generous headroom


def gpu_memory_mib() -> dict[str, int] | None:
    """Device-level used/total memory via nvidia-smi: the number that decides 'will it OOM'.

    Works for every engine, including vLLM whose worker is a separate process (torch in this
    process cannot see it). Returns None when there is no GPU (local tests)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.splitlines()[0]
        used, total = (int(x) for x in out.split(","))
        return {"used": used, "total": total}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class GpuPeakMonitor:
    """Background poller keeping the maximum nvidia-smi 'used' value since the last reset."""

    def __init__(self, interval_s: float = 0.25):
        self.interval_s = interval_s
        self.peak_used_mib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if gpu_memory_mib() is not None:
            self._thread.start()

    def reset(self) -> None:
        mem = gpu_memory_mib()
        self.peak_used_mib = mem["used"] if mem else 0

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            mem = gpu_memory_mib()
            if mem and mem["used"] > self.peak_used_mib:
                self.peak_used_mib = mem["used"]


def create_app(
    engine,
    token: str,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    monitor: GpuPeakMonitor | None = None,
):
    api = FastAPI()
    scheme = HTTPBearer(auto_error=False)
    state = {"in_flight": 0, "max_in_flight": 0, "served": 0, "failed": 0, "started": time.time()}

    def require_token(creds: HTTPAuthorizationCredentials | None = Depends(scheme)) -> None:
        if creds is None or not hmac.compare_digest(creds.credentials, token):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def _write_temp(data: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            f.write(data)
            return f.name

    def _probe(path: str) -> None:
        librosa.load(path, sr=SAMPLE_RATE, duration=5)  # cheap decodability check

    @api.get("/healthz")
    def healthz():
        return {"ok": True}

    @api.get("/stats", dependencies=[Depends(require_token)])
    def stats(reset_peak: bool = False):
        body = {
            **engine.info(),
            "gpu_mib": gpu_memory_mib(),
            "gpu_peak_used_mib": monitor.peak_used_mib if monitor else None,
            "requests": {k: v for k, v in state.items() if k != "started"},
            "uptime_s": round(time.time() - state["started"], 1),
        }
        if reset_peak and monitor:
            monitor.reset()
        return body

    @api.post("/", dependencies=[Depends(require_token)])
    async def caption(response: Response, audio: UploadFile = File(...)):
        t0 = time.perf_counter()
        data = await audio.read(max_upload_bytes + 1)
        if not data:
            raise HTTPException(422, "empty audio upload")
        if len(data) > max_upload_bytes:
            raise HTTPException(413, "audio too large")
        path = None
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            path = await asyncio.to_thread(_write_temp, data)
            try:
                await asyncio.to_thread(_probe, path)
            except Exception:
                raise HTTPException(422, "could not decode audio") from None
            try:
                result = await engine.caption(path)
            except Exception:
                state["failed"] += 1
                log.exception("engine failure")
                raise HTTPException(502, "captioning failed") from None
        finally:
            state["in_flight"] -= 1
            if path and os.path.exists(path):
                os.remove(path)
        text = clean_caption(result.text)
        if not text:
            state["failed"] += 1
            raise HTTPException(502, "model returned an empty caption")
        state["served"] += 1
        timings = {
            **result.timings,
            "api_total_s": time.perf_counter() - t0,
            "upload_bytes": float(len(data)),
        }
        log.info("caption timings %s", json.dumps({k: round(v, 4) for k, v in timings.items()}))
        response.headers["X-MF-Timings"] = json.dumps({k: round(v, 4) for k, v in timings.items()})
        return {"caption": text}

    return api
