"""Latency / throughput / GPU-memory benchmark for the deployed endpoint (client side).

    uv run python bench/bench.py --label vllm-l40s           # URL/token from env or ../.token
    uv run python bench/bench.py --label hf-l40s --conc 1,2  # baseline can't batch: keep it small

Env: MUSIC_FLAMINGO_ENDPOINT_URL (default: the deployed URL in README),
MUSIC_FLAMINGO_API_KEY or modal_app/.token.
The token is never printed. Output: bench/results/<label>.json + a markdown table on stdout.

What it measures (all wall-clock from the client, plus the server's X-MF-Timings header):
  first     first request of the run (cold container if the app was scaled to zero)
  seq       each track alone, repeated: steady-state single-request latency
  repeat    the same track again right away: shows prefix-cache effect (vLLM) vs none (HF)
  conc K    K requests fired at once: per-request latency and makespan -> songs/minute
GPU memory: /stats before and after (nvidia-smi used/total, and the peak since reset).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
DEFAULT_URL = "https://jawaharas198--music-flamingo-musicflamingo-web.us-east.modal.run"


def credentials() -> tuple[str, str]:
    url = os.environ.get("MUSIC_FLAMINGO_ENDPOINT_URL", DEFAULT_URL).rstrip("/")
    key = os.environ.get("MUSIC_FLAMINGO_API_KEY", "")
    if not key and (HERE.parent / ".token").exists():
        key = (HERE.parent / ".token").read_text().strip()
    if not key:
        raise SystemExit("no token: set MUSIC_FLAMINGO_API_KEY or create modal_app/.token")
    return url, key


def proxy_headers() -> dict[str, str]:
    """Modal proxy-token headers (the endpoint rejects requests without them at Modal's edge)."""
    key, secret = (
        os.environ.get("MUSIC_FLAMINGO_PROXY_KEY"),
        os.environ.get("MUSIC_FLAMINGO_PROXY_SECRET"),
    )
    file = HERE.parent / ".proxy-token.json"
    if not (key and secret) and file.exists():
        token = json.loads(file.read_text())
        key, secret = token["Modal-Key"], token["Modal-Secret"]
    return {"Modal-Key": key, "Modal-Secret": secret} if key and secret else {}


async def one(client: httpx.AsyncClient, url: str, key: str, track: str) -> dict:
    data = (AUDIO / track).read_bytes()
    t0 = time.perf_counter()
    try:
        r = await client.post(
            url + "/",
            headers={"Authorization": f"Bearer {key}", **proxy_headers()},
            files={"audio": (track, data, "audio/mpeg")},
        )
        wall = time.perf_counter() - t0
        server = json.loads(r.headers.get("x-mf-timings", "{}"))
        words = len(r.json().get("caption", "").split()) if r.status_code == 200 else 0
        return {
            "track": track,
            "status": r.status_code,
            "wall_s": wall,
            "words": words,
            "server": server,
            "caption": r.json().get("caption") if r.status_code == 200 else r.text[:200],
        }
    except httpx.HTTPError as e:
        return {
            "track": track,
            "status": -1,
            "wall_s": time.perf_counter() - t0,
            "error": repr(e),
            "server": {},
        }


async def stats(client, url, key, reset=False) -> dict:
    r = await client.get(
        url + "/stats",
        headers={"Authorization": f"Bearer {key}", **proxy_headers()},
        params={"reset_peak": reset},
    )
    return r.json() if r.status_code == 200 else {"error": r.status_code}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--reps", type=int, default=3, help="sequential repeats per track")
    ap.add_argument("--tracks", default="song_1.mp3,song_2.mp3,long_600s.mp3")
    ap.add_argument("--conc", default="1,4,8", help="comma list of concurrency levels")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    url, key = credentials()
    tracks = a.tracks.split(",")
    out: dict = {
        "label": a.label,
        "url": url,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs": [],
    }

    async with httpx.AsyncClient(timeout=a.timeout) as c:
        out["stats_before"] = await stats(c, url, key, reset=True)  # also wakes a cold container
        print("stats_before:", json.dumps(out["stats_before"]))

        first = await one(c, url, key, tracks[0])
        out["runs"].append({"phase": "first", **first})
        print(f"first   {first['track']:<18} {first['status']} {first['wall_s']:6.1f}s")

        for t in tracks:
            for i in range(a.reps):
                r = await one(c, url, key, t)
                out["runs"].append({"phase": "seq", "rep": i, **r})
                print(f"seq     {t:<18} {r['status']} {r['wall_s']:6.1f}s  server={r['server']}")

        r = await one(c, url, key, tracks[0])
        out["runs"].append({"phase": "repeat", **r})
        print(f"repeat  {tracks[0]:<18} {r['status']} {r['wall_s']:6.1f}s")

        for k in (int(x) for x in a.conc.split(",")):
            batch = [
                tracks[i % min(2, len(tracks))] for i in range(k)
            ]  # alternate the two short songs
            t0 = time.perf_counter()
            res = await asyncio.gather(*(one(c, url, key, t) for t in batch))
            makespan = time.perf_counter() - t0
            ok = [x for x in res if x["status"] == 200]
            api = [
                x["server"].get("api_total_s", 0) for x in ok
            ]  # server-side: excludes client upload/download
            eng = [x["server"].get("engine_s") or x["server"].get("generate_s") or 0 for x in ok]
            out["runs"].append(
                {
                    "phase": "conc",
                    "k": k,
                    "makespan_s": makespan,
                    "ok": len(ok),
                    "songs_per_min": len(ok) / makespan * 60,
                    "wall_s": [x["wall_s"] for x in res],
                    "statuses": [x["status"] for x in res],
                    "server_api_total_s": api,
                    "server_engine_s": eng,
                }
            )
            p50 = statistics.median(x["wall_s"] for x in res)
            eng_p50 = statistics.median(eng) if eng else 0
            api_max = max(api) if api else 0
            print(
                f"conc {k:<3} ok={len(ok)}/{k} makespan={makespan:6.1f}s p50={p50:5.1f}s "
                f"songs/min={len(ok) / makespan * 60:5.1f} "
                f"| server: engine p50={eng_p50:5.1f}s max api={api_max:5.1f}s"
            )

        out["stats_after"] = await stats(c, url, key)
        print("stats_after:", json.dumps(out["stats_after"]))

    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"{a.label}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {path}")

    header = "| phase | track | status | wall s | server s | prompt tok | out tok |"
    print("\n" + header + "\n|---|---|---|---|---|---|---|")
    for r in out["runs"]:
        if r["phase"] == "conc":
            continue
        s = r.get("server", {})
        srv = s.get("engine_s") or s.get("generate_s") or 0
        print(
            f"| {r['phase']} | {r['track']} | {r['status']} | {r['wall_s']:.1f} | {srv:.1f} | "
            f"{int(s.get('prompt_tokens', 0))} | {int(s.get('completion_tokens', 0))} |"
        )


if __name__ == "__main__":
    asyncio.run(main())
