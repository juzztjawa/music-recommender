"""Optimised engine: vLLM AsyncLLM (continuous batching, paged KV cache, prefix caching).

Concurrent requests are batched by vLLM's scheduler, not by us. Exposes ``await start()``,
``await caption(path) -> CaptionResult`` and ``info()``.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from transformers import AutoTokenizer
from vllm import AsyncEngineArgs, SamplingParams
from vllm.sampling_params import RequestOutputKind
from vllm.v1.engine.async_llm import AsyncLLM

from flamingo.common import PROMPT, SAMPLE_RATE, CaptionResult, load_audio


class VLLMEngine:
    name = "vllm"

    def __init__(
        self,
        model_id: str,
        revision: str,
        max_new_tokens: int
        | None,  # None: generate until end-of-text (context window is the bound)
        *,
        gpu_memory_utilization: float,
        max_model_len: int,
        max_num_seqs: int,
        quantization: str | None,
        enforce_eager: bool,
    ):
        self.model_id, self.revision, self.max_new_tokens = model_id, revision, max_new_tokens
        self.cfg = {
            "gpu_memory_utilization": gpu_memory_utilization,
            "max_model_len": max_model_len,
            "max_num_seqs": max_num_seqs,
            "quantization": quantization,
            "enforce_eager": enforce_eager,
        }
        self.startup: dict[str, float] = {}

    async def start(self) -> None:
        t0 = time.perf_counter()
        args = AsyncEngineArgs(
            model=self.model_id,
            revision=self.revision,
            dtype="bfloat16",
            limit_mm_per_prompt={"audio": 1},
            enable_prefix_caching=True,  # same audio + same prompt -> prefill is skipped
            disable_log_stats=False,  # periodic throughput / KV-usage / prefix-hit log lines
            **self.cfg,
        )
        self.engine = AsyncLLM.from_engine_args(args)
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self.revision)
        # The HF chat template turns an audio part into the single `<sound>` placeholder; vLLM's
        # multimodal processor then expands it to ~750 tokens per 30 s window.
        self.prompt_text = tokenizer.apply_chat_template(
            [{"role": "user", "content": [{"type": "audio"}, {"type": "text", "text": PROMPT}]}],
            tokenize=False,
            add_generation_prompt=True,
        )
        self.startup = {"engine_start_s": time.perf_counter() - t0}

    async def caption(self, path: str) -> CaptionResult:
        t0 = time.perf_counter()
        wave = await asyncio.to_thread(load_audio, path)
        t1 = time.perf_counter()
        params = SamplingParams(
            max_tokens=self.max_new_tokens,
            temperature=0.0,
            output_kind=RequestOutputKind.DELTA,
        )
        prompt = {
            "prompt": self.prompt_text,
            "multi_modal_data": {"audio": (wave, SAMPLE_RATE)},
        }
        pieces: list[str] = []
        n_tokens = 0
        prompt_tokens = 0
        first = None
        async for out in self.engine.generate(prompt, params, uuid.uuid4().hex):
            if first is None:
                first = time.perf_counter()
                prompt_tokens = len(out.prompt_token_ids or [])
            comp = out.outputs[0]
            pieces.append(comp.text)
            n_tokens += len(comp.token_ids)
        t2 = time.perf_counter()
        first = first or t2
        return CaptionResult(
            "".join(pieces),
            {
                "audio_decode_s": t1 - t0,
                "ttft_s": first - t1,  # queue + audio features + prefill + 1st token
                "decode_s": t2 - first,
                "engine_s": t2 - t1,
                "prompt_tokens": float(prompt_tokens),
                "completion_tokens": float(n_tokens),
                "decode_tok_per_s": (n_tokens - 1) / (t2 - first)
                if t2 > first and n_tokens > 1
                else 0.0,
            },
        )

    def info(self) -> dict:
        return {
            "engine": self.name,
            "model": self.model_id,
            "revision": self.revision,
            **self.cfg,
            **self.startup,
        }
