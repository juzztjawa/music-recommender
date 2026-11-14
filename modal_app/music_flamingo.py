"""Music Flamingo audio-captioning endpoint on Modal — thin deployment wrapper.

Where things live:
  Dockerfile / pyproject.toml / uv.lock   the container environment (locked; no pip)
  flamingo/hf_engine.py, vllm_engine.py   the two inference engines (baseline / optimised)
  flamingo/api.py                         HTTP contract, auth, validation (tested without a GPU)
  flamingo/common.py                      prompt, caption cleanup, audio decoding
  this file                               image + GPU + scaling + lifecycle only

Deploy:   uv run modal deploy music_flamingo.py          (from modal_app/)
Stop:     uv run modal app stop music-flamingo --yes
Secret:   modal secret create music-flamingo-auth AUTH_TOKEN=<random string>

Tunables are read at *deploy* time from MF_* env vars and baked into the image env, so the running
container always sees the same values the decorator used.
"""

import logging
import os
import time
from pathlib import Path

import modal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("music-flamingo.coldstart")

HERE = Path(__file__).parent

# Exact commit of nvidia/music-flamingo-hf (checked 2026-11-07). Bump deliberately, never "main".
MODEL_ID = os.environ.get("MF_MODEL_ID", "nvidia/music-flamingo-hf")
MODEL_REVISION = os.environ.get("MF_MODEL_REVISION", "e560c33247f20e2f735c87ce9adebb8e53befe69")

ENGINE = os.environ.get("MF_ENGINE", "vllm")  # "vllm" (optimised) | "hf" (baseline)
GPU = os.environ.get("MF_GPU", "L40S")
SCALEDOWN_SECONDS = int(os.environ.get("MF_SCALEDOWN_SECONDS", "120"))
MAX_CONTAINERS = int(os.environ.get("MF_MAX_CONTAINERS", "5"))
# Requests one container accepts at once. vLLM batches them; the HF baseline cannot (lock).
CONCURRENCY = int(os.environ.get("MF_CONCURRENCY", "8" if ENGINE == "vllm" else "1"))

RUNTIME_ENV = {
    "MF_ENGINE": ENGINE,
    "MF_MODEL_ID": MODEL_ID,
    "MF_MODEL_REVISION": MODEL_REVISION,
    # Safety ceiling, not a target: captions normally stop on their own after ~500-700 tokens.
    # It only bounds a runaway generation (and its GPU bill). "" = no ceiling.
    "MF_MAX_NEW_TOKENS": os.environ.get("MF_MAX_NEW_TOKENS", "10000"),
    # vLLM knobs (ignored by the hf engine)
    "MF_GPU_MEM_UTIL": os.environ.get("MF_GPU_MEM_UTIL", "0.90"),
    # 10 min = 20 windows x 750 audio tokens = 15,000 (+ prompt + output); 20,480 leaves headroom.
    "MF_MAX_MODEL_LEN": os.environ.get("MF_MAX_MODEL_LEN", "20480"),
    "MF_MAX_NUM_SEQS": os.environ.get("MF_MAX_NUM_SEQS", str(CONCURRENCY)),
    "MF_QUANT": os.environ.get("MF_QUANT", ""),  # "" | "fp8"
    "MF_ENFORCE_EAGER": os.environ.get("MF_ENFORCE_EAGER", "0"),  # 1 = skip CUDA graphs/compile
}

app = modal.App("music-flamingo")
weights = modal.Volume.from_name("music-flamingo-weights", create_if_missing=True)
WEIGHTS_DIR = "/weights"

image = (
    modal.Image.from_dockerfile(HERE / "Dockerfile", context_dir=HERE)
    .env(
        {
            "HF_HOME": WEIGHTS_DIR,
            # torch.compile / CUDA-graph artefacts persist on the Volume -> warm cold starts.
            "VLLM_CACHE_ROOT": f"{WEIGHTS_DIR}/vllm-cache",
            "VLLM_USE_FLASHINFER_SAMPLER": "0",  # avoid a JIT (nvcc) dependency
            # The tokenizer config says model_max_length=8192, but the decoder (Qwen2.5-7B) is
            # 32,768 and a 10-min track alone is ~15,000 audio tokens. vLLM refuses the larger
            # value without this.
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
            **RUNTIME_ENV,
        }
    )
    .add_local_python_source("flamingo")  # must be last
)

# Packages that exist only in the image (torch, vLLM, ...). `image.imports()` is Modal's documented
# way to keep these imports at the top of the file: it runs them inside the container, and on a
# machine without them (your laptop, at deploy time) it records the ImportError instead of raising.
_IMPORTS_T0 = time.perf_counter()
with image.imports():
    import psutil
    from huggingface_hub import snapshot_download

    from flamingo.api import GpuPeakMonitor, create_app
    from flamingo.hf_engine import HFEngine
    from flamingo.vllm_engine import VLLMEngine
IMPORTS_S = time.perf_counter() - _IMPORTS_T0


@app.function(image=image, volumes={WEIGHTS_DIR: weights}, timeout=3600)
def download_weights():
    """One-off: `uv run modal run music_flamingo.py::download_weights`."""
    snapshot_download(MODEL_ID, revision=MODEL_REVISION)
    weights.commit()


def _build_engine():
    e = os.environ
    max_new_tokens = int(e["MF_MAX_NEW_TOKENS"]) if e["MF_MAX_NEW_TOKENS"] else None
    if e["MF_ENGINE"] == "hf":
        return HFEngine(
            e["MF_MODEL_ID"],
            e["MF_MODEL_REVISION"],
            max_new_tokens,
            max_model_len=int(e["MF_MAX_MODEL_LEN"]),
        )
    return VLLMEngine(
        e["MF_MODEL_ID"],
        e["MF_MODEL_REVISION"],
        max_new_tokens,
        gpu_memory_utilization=float(e["MF_GPU_MEM_UTIL"]),
        max_model_len=int(e["MF_MAX_MODEL_LEN"]),
        max_num_seqs=int(e["MF_MAX_NUM_SEQS"]),
        quantization=e["MF_QUANT"] or None,
        enforce_eager=e["MF_ENFORCE_EAGER"] == "1",
    )


@app.cls(
    image=image,
    gpu=GPU,
    volumes={WEIGHTS_DIR: weights},
    secrets=[modal.Secret.from_name("music-flamingo-auth")],
    scaledown_window=SCALEDOWN_SECONDS,
    max_containers=MAX_CONTAINERS,
    timeout=300,  # per request
    startup_timeout=1200,  # vLLM first start: weight load + torch.compile + CUDA-graph capture
)
@modal.concurrent(max_inputs=CONCURRENCY)
class MusicFlamingo:
    @modal.enter()
    async def load(self):
        t0 = time.perf_counter()
        # Seconds since this Python process was created: covers imports plus the interpreter start.
        log.info(
            "coldstart load() begins: process_age_s=%.1f imports_block_s=%.1f",
            time.time() - psutil.Process(os.getpid()).create_time(),
            IMPORTS_S,
        )
        self.engine = _build_engine()
        await self.engine.start()
        t1 = time.perf_counter()
        self.monitor = GpuPeakMonitor()
        self.monitor.start()
        weights.commit()  # persist compile caches written during start-up
        log.info(
            "coldstart load() done: engine_start_s=%.1f commit_s=%.1f load_total_s=%.1f",
            t1 - t0,
            time.perf_counter() - t1,
            time.perf_counter() - t0,
        )

    # Modal's proxy rejects requests without a valid proxy token (Modal-Key / Modal-Secret headers)
    # before any GPU container starts. The bearer-token check in flamingo/api.py stays as a second
    # layer.
    @modal.asgi_app(requires_proxy_auth=True)
    def web(self):
        return create_app(self.engine, os.environ["AUTH_TOKEN"], monitor=self.monitor)
