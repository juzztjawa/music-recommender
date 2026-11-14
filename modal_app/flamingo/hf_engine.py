"""Baseline engine: Hugging Face transformers ``generate``, one request at a time.

Kept deliberately simple so the vLLM numbers have something honest to beat. Exposes
``await start()``, ``await caption(path) -> CaptionResult`` and ``info()``.
"""

from __future__ import annotations

import asyncio
import threading
import time

import torch
from transformers import AudioFlamingo3ForConditionalGeneration, AutoProcessor

from flamingo.common import PROMPT, CaptionResult


class HFEngine:
    name = "hf"

    def __init__(
        self, model_id: str, revision: str, max_new_tokens: int | None, *, max_model_len: int
    ):
        self.model_id, self.revision, self.max_new_tokens = model_id, revision, max_new_tokens
        self.max_model_len = max_model_len
        self.startup: dict[str, float] = {}

    async def start(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        t0 = time.perf_counter()
        self.processor = AutoProcessor.from_pretrained(self.model_id, revision=self.revision)
        self.model = AudioFlamingo3ForConditionalGeneration.from_pretrained(
            self.model_id, revision=self.revision, torch_dtype=torch.bfloat16, device_map="auto"
        ).eval()
        self.lock = threading.Lock()  # one generate() at a time
        self.startup = {
            "load_s": time.perf_counter() - t0,
            "weights_allocated_gib": torch.cuda.memory_allocated() / 2**30,
        }

    async def caption(self, path: str) -> CaptionResult:
        return await asyncio.to_thread(self._caption, path)

    def _caption(self, path: str) -> CaptionResult:
        t0 = time.perf_counter()
        conversation = [
            {
                "role": "user",
                "content": [{"type": "text", "text": PROMPT}, {"type": "audio", "path": path}],
            }
        ]
        inputs = self.processor.apply_chat_template(
            conversation, tokenize=True, add_generation_prompt=True, return_dict=True
        ).to(self.model.device)
        # Processor emits fp32 features; weights are bf16 -> cast floating tensors only.
        for k, v in inputs.items():
            if hasattr(v, "is_floating_point") and v.is_floating_point():
                inputs[k] = v.to(self.model.dtype)
        t1 = time.perf_counter()
        with self.lock:
            torch.cuda.reset_peak_memory_stats()
            t2 = time.perf_counter()
            # No new-token cap: generate until end-of-text, bounded by the context window
            # (`max_length` counts prompt + output; transformers' default would be only 20).
            length = (
                {"max_new_tokens": self.max_new_tokens}
                if self.max_new_tokens
                else {"max_length": self.max_model_len}
            )
            out = self.model.generate(**inputs, **length, do_sample=False)
            torch.cuda.synchronize()
            t3 = time.perf_counter()
            peak_alloc = torch.cuda.max_memory_allocated() / 2**30
            peak_resv = torch.cuda.max_memory_reserved() / 2**30
        new = out[:, inputs.input_ids.shape[1] :]
        text = self.processor.batch_decode(new, skip_special_tokens=True)[0]
        return CaptionResult(
            text,
            {
                "prep_s": t1 - t0,
                "lock_wait_s": t2 - t1,
                "generate_s": t3 - t2,
                "prompt_tokens": float(inputs.input_ids.shape[1]),
                "completion_tokens": float(new.shape[1]),
                "peak_allocated_gib": peak_alloc,
                "peak_reserved_gib": peak_resv,
            },
        )

    def info(self) -> dict:
        return {
            "engine": self.name,
            "model": self.model_id,
            "revision": self.revision,
            **self.startup,
        }
