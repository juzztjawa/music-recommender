# Modal container cold start: notes for analysis

Handoff for a session whose job is to **understand and reduce the cold start** of the Music Flamingo
endpoint. Everything marked *measured* comes from runs on this project (dates given); everything marked
*hypothesis* is untested. Read `CODING_STANDARDS.md` and `CLAUDE.md` first.

## 1. What a cold start is here

The first request after the container scaled to zero (idle longer than `scaledown_window`, 120 s since 2026-11-09; it was 600 s before) waits for
a new container: GPU allocation, image start, Python imports, vLLM engine start-up, then the request itself.
Nothing is served until `@modal.enter()` (`MusicFlamingo.load`) returns; Modal does not count a container as
warm before that.

Why it hurts: the backend calls the endpoint from the audio-analysis tool (`analyze_audio`) with a 90 s HTTP
timeout. The cold start is longer than that when the cache is cold, so the **first song after idle fails**
with a captioning error (the agent continues from the title alone).

## 2. Setup under test

| Item | Value |
|---|---|
| Entry point | `modal_app/music_flamingo.py` (image, GPU, scaling, `@modal.enter` lifecycle only) |
| Engine code | `modal_app/flamingo/vllm_engine.py` `VLLMEngine.start()`; baseline `hf_engine.py` |
| Image | built from `modal_app/Dockerfile` + `uv.lock` (Python 3.12, vLLM 0.33.0, torch 2.14.0, transformers 5.20.2, Modal 1.6.3) |
| GPU / region | L40S (46 GB), us-east (`...us-east.modal.run`) |
| Model | `nvidia/music-flamingo-hf` pinned to commit `e560c332...`, bf16, about 8B parameters (about 16 GB of weights, estimate) |
| vLLM settings | `gpu_memory_utilization=0.90`, `max_model_len=20480`, `max_num_seqs=8`, prefix caching on, `enforce_eager=False` (so **torch.compile + CUDA-graph capture run at start-up**), `limit_mm_per_prompt={"audio":1}` |
| Weights | Modal Volume `music-flamingo-weights` mounted at `/weights` (`HF_HOME=/weights`); `weights.commit()` is called after the engine starts |
| Compile cache | `VLLM_CACHE_ROOT=/weights/vllm-cache` (on the same Volume, so artefacts can survive container restarts) |
| Other env | `VLLM_USE_FLASHINFER_SAMPLER=0`, `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` |
| Timeouts | `startup_timeout=1200`, request `timeout=300`, `scaledown_window=120` (was 600) |
| Billing | about $1.95/h on the L40S while a container is up, including start-up and idle time |

## 3. Measurements so far

| What | Number | Source / date |
|---|---|---|
| Cold request, end to end, first deploy of the vLLM image | **112 to 119 s** (one run: 118.8 s) | e2e agent runs and warm-up call, 2026-11-08 |
| `engine_start_s` (inside `VLLMEngine.start()`) in that period | **77.4 s** | `modal_app/bench/results/vllm-l40s-bf16*.json`, `stats_before`, 2026-11-07 |
| Cold `GET /healthz` after the 2026-11-09 redeploy | **72.9 s** wall | this session |
| `engine_start_s` after that redeploy | **35.4 s** | `/stats`, same container, 2026-11-09 |
| Time outside the engine start (scheduling, image start, imports, Modal overhead) | roughly **35 to 40 s** (73 minus 35 is same-day; 112-119 minus 77 mixes 11-08 and 11-07 runs on different images, so only approximate) | derived; not broken down further |
| HF baseline engine: model load | **32.7 s** (no compile, no graph capture) | HF engine run, 2026-11-07 |
| `modal deploy` image build | 103 to 129 s | not a cold start; happens once per image change |
| First-ever start | extra time for the weight download into the Volume (about 75 s for 20 files, via `download_weights`) and an empty compile cache | 2026-11-02 |
| Authenticated cold `GET /healthz` after the 2026-11-09 proxy-auth redeploy (image unchanged, 6 s deploy) | **178.8 s** wall, with `engine_start_s` only **41.5 s**, so about **137 s** was outside the engine start | this session, 16:5x IST; explained in 3b: about 113 s of it was waiting for an L40S to become available |
| Unauthenticated request after enabling proxy auth | 401 in 1.0 s, **no container started** | this session |
| Warm request, same song | about 6 to 7 s (decode-bound, 49 tok/s) | benchmark JSONs |

What the two engine-start numbers (77 s and 35 s) say: the same code started about twice as fast on the
later run. **Hypothesis:** the torch.compile/Inductor and CUDA-graph artefacts in `/weights/vllm-cache` were
reused (the Volume had been committed by earlier containers). **Not verified**; the logs of those runs were
not kept.

**Not measured yet (the main gap):** the per-stage split inside the 35 to 77 s. vLLM logs it; we did not
capture it. Lines to look for: `Model loading took ... GiB and ... seconds`, `torch.compile takes ... s`,
`Directly load the compiled graph` (cache hit) or compile messages (cache miss), `Graph capturing finished in
... secs`, `init engine (profile, create kv cache, warmup model) took ... seconds`,
`Available KV cache memory`, `GPU KV cache size`. Same for the time before Python starts (image pull, mount of
the Volume) and the imports in the `with image.imports():` block (`torch`, `vllm`, `transformers`,
`librosa`).

### 3a. Stage breakdown, 2026-11-09 (measured, compile cache WARM, L40S, current image)

One cold `GET /healthz`: **49.8 s** wall (container log says 48.8 s). Logging added in `music_flamingo.py`
(`coldstart` log lines: process age, import-block time, `load()` total) plus vLLM's own lines.

| Stage | Seconds | Source |
|---|---|---|
| Request to Python process start (scheduling, container boot) | about 3 | request time vs process create time |
| Image/Volume mount, interpreter, `with image.imports():` block | **15.1** (imports alone 13.7) | `process_age_s`, `imports_block_s` |
| `load()` total | **31.6** | `load_total_s` (`engine_start_s` 31.5, `weights.commit()` 0.1) |
| inside `load()`: engine-core subprocess spawn and its own imports (09:52:01 to 09:52:10) | about **9** | log timestamps |
| inside `load()`: distributed init, model init | about 4 | log timestamps |
| inside `load()`: weights from the Volume (15.4 GiB, 9P filesystem) | **9.2** (6.0 reading) | `Model loading took` |
| inside `load()`: encoder profiling plus compile-cache load | about 4 (torch.compile 0.90 s: AOT cache **hit**) | `Directly load AOT compilation`, `torch.compile took` |
| inside `load()`: CUDA-graph capture (two passes) | about 2 | `Graph capturing finished in 1 secs` x2 |
| inside `load()`: KV cache, warmup, tokenizer and chat template | about 3 | log timestamps |

Findings:
- The compile cache **is** reused (AOT load, 0.9 s). Compile plus graph capture is only about 3 s now, so
  `enforce_eager` can save at most that and is not worth the slower decode.
- The two biggest blocks are **Python imports in the main process (13.7 s)** and the **engine-core
  subprocess start (about 9 s, imports torch/vllm again)**. Both are Python start-up work, which is
  what a memory snapshot targets.
- Dropping the HF engine import saves nothing: `import flamingo.vllm_engine` alone takes 9.7 s in the warm
  container, adding `hf_engine` changes it by about 0 (its imports are a subset). `vllm` plus `transformers`
  plus `torch` are the cost. The 232 locked packages are mostly vLLM's own hard dependencies.
- Weight read is 6 s of 15.4 GiB (about 2.5 GiB/s) from the Volume; not the bottleneck.
- Per-stage logs are saved only in the session scratchpad; the numbers above are the record.
- Warm captions (no token cap, current prompt): 10.7 to 12.8 s engine time for 490 to 630 tokens at
  about 49 tok/s (decode-bound; 10.7 to 12.8 s API time); total 16 to 22 s including the upload from the laptop.
- Run cost: container up about 5 min, about $0.16.
- Not yet measured: the **cold-cache** variant (needs the Volume cache cleared).

### 3b. The 178.8 s run explained (from the app log of that container, 2026-11-09, no new paid run)

The first line of that container's log is: *"Function 'MusicFlamingo.*' is waiting to be scheduled on a
GPU_L40S worker. We are actively working on acquiring more capacity for your workload."* So the big gap
was **waiting for an L40S, before any of our code ran**.

| Part of the 178.8 s | Seconds | How derived |
|---|---|---|
| Before the Python process existed (L40S capacity wait, container boot) | about **113** | wall minus container-side time; the request start time is not in the log, so approximate |
| Process start to `load()` begins (imports block 21.0 s) | 23.8 | `process_age_s`, `imports_block_s` |
| `load()` (`engine_start_s` 41.6; weights 12.3 s, `torch.compile` 1.3 s as AOT cache hit, init engine 12.1 s) | 41.6 | `load_total_s` |
| Container-side total (process created 11:24:32 to ready 11:25:38 UTC) | **65.5** | log timestamps |

Compared with the 49.8 s run (3a): the container-side part was 65.5 s vs about 47 s (imports 21.0 vs 13.7 s,
weights 12.3 vs 9.2 s, init engine 12.1 vs 9.2 s). So even without a capacity wait, start-up varies by
about 40 % between runs. Conclusion: cold start = **capacity wait (0 to 110+ s, not controllable in code) +
container start-up (47 to 66 s, mostly Python imports and engine subprocess)**. Hypotheses, not tested: a
GPU fallback list in `gpu=[...]` (check the Modal docs for the exact syntax and which GPUs fit the model at
`gpu_memory_utilization=0.90`), and warming the endpoint early so the wait overlaps other work.

## 4. How to measure (recipe, costs about $0.07 to 0.15 per cold start)

```bash
cd modal_app
uv run modal deploy music_flamingo.py                       # builds/pushes the image if it changed
uv run modal app logs music-flamingo > /tmp/cold.log &      # note the PID; kill by PID, not pkill -f
curl -sL -m 400 -w "total=%{time_total}s\n" -o /dev/null \
  https://jawaharas198--music-flamingo-musicflamingo-web.us-east.modal.run/healthz
curl -sL -H "Authorization: Bearer $(cat .token)" <URL>/stats    # engine_start_s, uptime_s
uv run modal app stop music-flamingo --yes                   # ALWAYS stop afterwards
```

Rules: never print `.token`; a start-up crash makes Modal retry in a loop that keeps billing, so stop the app
immediately if the log shows a repeating error; web requests longer than about 150 s answer HTTP 303, so use
`curl -L` / follow redirects. For a clean comparison run each variant twice (once with a cold compile cache,
once with it warm) and record both. Add a timing breakdown to the log (for example timestamps around
`load()` stages) only if the log lines above are not enough.

## 5. Candidate levers (all hypotheses unless stated; verify against the docs before relying on them)

Modal's own guidance (verified in the docs, <https://modal.com/docs/guide/cold-start> and
<https://modal.com/docs/guide/memory-snapshots>): containers boot in about one second, so the time is
global-scope code and `@modal.enter` work; keep models in an Image or Volume (already done); load independent
files concurrently; Memory Snapshots capture state after warm-up and are described as 3 to 10 times faster for
init-heavy functions.

| Lever | What it changes | Risk / caveat |
|---|---|---|
| **GPU memory snapshot** (`enable_memory_snapshot=True`, `experimental_options={"enable_gpu_snapshot": True}`, GPU init in `@modal.enter(snap=True)`) | Could skip imports, weight load and warm-up on restore | Modal labels GPU snapshots **alpha**; docs say snapshots do not speed up reading weights from storage, that `torch.compile` can make snapshot creation fail (`TORCHINDUCTOR_COMPILE_THREADS=1` may help), that an unfilled KV cache should be discarded before the snapshot, and that multi-GPU code is mostly incompatible. vLLM's `AsyncLLM` runs its engine core in a **separate process**; the docs do not say how that interacts with snapshots. Needs a spike. |
| CPU-only snapshot | Captures imports (`torch`, `vllm`, `transformers`) only | GPU is unavailable in `snap=True`; smaller gain |
| Confirm the compile cache is really reused | Avoids re-running torch.compile each cold start | Check cache hit lines in the log; check the Volume is committed and reloaded; vLLM keys the cache on model, config and code hash, so a vLLM or config change invalidates it |
| `enforce_eager=True` (`MF_ENFORCE_EAGER=1`) | Skips compile and graph capture: faster start | Slower decode per token (graph replay is what keeps decode near the memory-bandwidth limit); measure the cost per caption |
| Fewer captured CUDA-graph sizes / lower compilation level | Shorter capture | Need to look up the exact vLLM 0.33 `compilation_config` options; `max_num_seqs=8` already limits the sizes |
| FP8 weights (`MF_QUANT=fp8`) | Half the bytes to load and to stream per token | Quality not checked; first start with FP8 recompiles |
| Faster weight loading | Check Volume read throughput; try a larger `load_format`/threads, or bake the weights into the image layer | Image gets about 16 GB larger; image build and push time grow |
| Reduce import time | Profile with `python -X importtime`; drop the HF-engine import from the vLLM container (today both engines are imported in `with image.imports():`) | Small gain, easy to measure |
| Keep it warm | `scaledown_window` up to 20 min; `min_containers=1` | Idle GPU time is billed: `min_containers=1` is about $47 a day. Not recommended. |
| **Warm it before the user needs it** | The frontend or backend fires `/healthz` at sign-in or when the user starts typing, so the cold start overlaps with the agent's own 30 to 90 s of other work | No GPU change; needs a small backend/frontend change. Probably the cheapest real win. |
| Backend tolerance | `MUSIC_FLAMINGO_TIMEOUT_SECONDS` above the cold start (the client already raises on timeout), and `follow_redirects=True` for Modal's 303 on long requests | Fixes the failure, not the wait |

## 6. Constraints for whoever picks this up

- Paid runs: say what they cost first, keep notes of each run, and **stop the app afterwards**.
- No unrequested code changes; no commits unless asked; follow `CODING_STANDARDS.md` (imports at the top,
  Modal image-only packages via `with image.imports():`).
- Dependencies through `uv` only; the image installs the `serve` group from `modal_app/uv.lock`.
- Update `SETUP.md` and this doc when something changes; record every measurement with date, config and
  whether the compile cache was cold or warm.
- Do not edit `backend/app/clients/reddit_composio.py` or the playlist/Reddit files (another session owns them).

## 7. Related files

`modal_app/music_flamingo.py`, `modal_app/flamingo/vllm_engine.py`, `modal_app/flamingo/api.py` (`/stats`,
`/healthz`), `modal_app/Dockerfile`, `modal_app/pyproject.toml`, `modal_app/bench/bench.py` (its first phase
records the cold request), `modal_app/bench/results/*.json`, `modal_app/README.md` (history),
`backend/app/clients/music_flamingo.py` (timeout, no redirect handling).
