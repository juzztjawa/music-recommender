"""Code shared by both engines and the HTTP layer. Light dependencies only (numpy, librosa)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import librosa
import numpy as np

# Prose-only and as detailed as the model wants: the recommendation agent benefits from more
# information, so there is deliberately no word limit.
PROMPT = (
    "Describe this track in plain prose, as thoroughly as you can. "
    "No markdown, no lists, no headings, no quoted lyrics, no mention of duration. "
    "Cover genre, tempo, key, instrumentation, energy and dynamics, mood, how the song "
    "progresses, and production/ambience. Be concrete."
)
SAMPLE_RATE = 16_000
MAX_AUDIO_SECONDS = 600  # model card: 30 s windows, 10-minute cap (longer input is truncated)


@dataclass
class CaptionResult:
    text: str
    timings: dict[str, float] = field(default_factory=dict)  # seconds / counts, for the latency doc


def clean_caption(text: str) -> str:
    """Strip markdown, collapse whitespace, trim a token-limit cut-off to the last full sentence."""
    text = re.sub(r"[*_#`]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?\"'":
        cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
        if cut > 0:
            text = text[: cut + 1]
    return text


def load_audio(path: str) -> np.ndarray:
    """Decode to mono float32 at 16 kHz, truncated to the model's 10-minute cap."""
    wave, _ = librosa.load(path, sr=SAMPLE_RATE, mono=True, duration=MAX_AUDIO_SECONDS)
    return wave
