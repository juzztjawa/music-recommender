# modal_app — Music Flamingo audio captioning on Modal

**Status (2026-11-02): deployed, tested by curl, then STOPPED (no cost while stopped).**
Endpoint behaviour is verified with curl (§9). **Not yet verified:** the backend end to end
(`analyze-audio`, `/api/chat/stream`, failure path), the licence read, a no-persistence check on
the container, and before/after recommendation quality. To use it again: redeploy (see
`SETUP.md` → "Audio captioning endpoint"). Endpoint URL (changes only if app/workspace renamed):
`https://jawaharas198--music-flamingo-musicflamingo-web.us-east.modal.run`

## 1. What this is and why
Orchestra recommends music by first understanding *why* the user likes their input songs. The
backend downloads each input song's audio (yt-dlp → mp3) and posts it to an endpoint that returns a
text **caption** (instrumentation, tempo, energy, mood, progression). The supervisor agent writes
search hypotheses from it. Until this service exists, `MUSIC_FLAMINGO_ENDPOINT_URL` is empty, every
caption is `null`, and the backend skips the YouTube download.

This folder holds that endpoint. It is deployed separately from `backend/` and has its own
`pyproject.toml` / `.venv` (managed with **uv**; no pip).

## 2. Steps done so far (chronological)
1. **Read the handoff** (`docs/modal-handoff.md`) and the backend files it points to:
   `clients/music_flamingo.py` (the contract), `agents/audio.py` (never raises; skips when
   unconfigured), config + `.env.example`. Confirmed: no `modal_app/` existed, Modal not installed,
   no Modal auth.
2. **Checked the model card and current Modal docs** instead of trusting memory (the handoff warns
   Modal API names drift). Findings:
   - `nvidia/music-flamingo-hf` is **8B** params (BF16), not 7B as the handoff says. Weights ≈ 16 GB.
   - Licence: **NVIDIA OneWay Noncommercial** ("non-commercial research purposes only"), plus Qwen
     terms for parts of the data. Fine for this non-commercial project; **I have not yet read the
     full licence text** — still required before real testers use it.
   - Audio is processed in 30 s windows; the card says a 10-minute cap in one place and 20 minutes in
     another (inconsistent). The backend caps source at ~29 min (the 40 MB upload limit); the model itself only hears the first 10 min.
   - Not gated (no HF token needed).
   - Modal: `@modal.asgi_app()` for the web app, `scaledown_window` max **1200 s** (default 60),
     `max_containers`, Volumes and Secrets as used in the code.
3. **Wrote `music_flamingo.py`** (see §4).
4. **Environment:** created `modal_app/pyproject.toml` (dep: `modal`). Initially I suggested a
   root-level `python -m venv` + pip; you correctly rejected that — everything now lives inside
   `modal_app/` and uses uv. Saved as a memory so it isn't repeated.
5. **Compared alternative models** (you asked about MOSS-Music), see §6.
6. **Modal account:** you ran `modal token new` and created the secret `music-flamingo-auth`
   (key `AUTH_TOKEN`, random value, never shown in chat). Verified: `modal profile current` works
   and the secret is listed.
7. **First deploy attempt** (`modal run music_flamingo.py::download_weights`): the container image
   built fine, then Modal rejected the app: *"Please add a payment method to use L40S GPU
   functions."* No weights downloaded yet, nothing deployed.

## 3. Decisions (from the handoff, plus mine)
| Decision | Choice | Source |
|---|---|---|
| Model | `nvidia/music-flamingo-hf` | handoff (settled); you confirmed "go with Music Flamingo" |
| Host | Modal, scale-to-zero + warm window | handoff |
| GPU | **L40S (48 GB)**, env `MF_GPU` | mine — 8B BF16 + audio activations looked tight on 24 GB; **unmeasured** |
| Warm window | `scaledown_window=120 s` (`MF_SCALEDOWN_SECONDS`; was 600 s until 2026-11-09, cut to save idle GPU cost) | your decision; handoff wanted 10–15 min, Modal max is 20 |
| Parallelism | `max_containers=5`, one `generate()` at a time per container (lock) | mine — five songs at once means up to 5 containers; each may cold-start |
| Auth | Bearer token from Modal secret, `hmac.compare_digest`, 401 if wrong/missing | handoff |
| Audio handling | temp file per request, deleted in `finally`; never on a Volume | handoff ("process and discard") |
| Prompt | one-paragraph plain prose, no markdown, covers genre/tempo/key/instrumentation/energy/mood/progression/production; `max_new_tokens=400`, greedy | mine; tunable (`PROMPT` constant) |

## 4. What `music_flamingo.py` does
(Layout since 2026-11-09: `music_flamingo.py` is only the Modal wiring; the code is in the `flamingo/` package:
`api.py`, `common.py`, `hf_engine.py`, `vllm_engine.py`. Image-only imports use `with image.imports():`.
The default engine is vLLM; the numbers and the `max_new_tokens=400` mentioned in older sections below
predate that.)
- `POST /` with multipart field `audio` → `200 {"caption": "..."}`.
- No/wrong token → `401`. Empty upload → `422`. Undecodable audio (librosa 5-second probe) → `422`.
  Over 40 MB → `413`. Empty model output → `502`. Never a `200` with an error body.
- Weights are cached in the Modal Volume `music-flamingo-weights` (`HF_HOME=/weights`), populated by
  `download_weights`, so cold starts don't re-download.

## 5. What happened after the payment method was added
1. `download_weights` → 20 files into the Volume in ~75 s.
2. `modal deploy` → endpoint live. Secret token rotated by you into `modal_app/.token` (gitignored)
   because Modal can't read secret values back; I never saw the token.
3. First real song → **500**: `Input type (float) and bias type (BFloat16) should be the same`
   (processor emits fp32 features, weights are bf16). Fixed by casting floating inputs to the model dtype.
   (The model class `AudioFlamingo3ForConditionalGeneration` loads fine under transformers 5.22.1.)
4. A redeploy kept an old container alive for a while (one more 500). `modal app stop … --yes` then
   redeploy cleared it. Lesson: after changing code, stop first to avoid stale containers.
5. First captions were too long, had markdown and quoted lyrics, and were cut mid-sentence at the token
   limit. Fixed: tighter prompt (≤120 words, no markdown/lyrics/duration), `max_new_tokens=300`, and a
   `_clean()` step that strips markdown and trims a truncated tail to the last full sentence.
   The model still adds "The duration of the piece is N seconds" despite the instruction — harmless.
6. Stopped the app at the end; `modal container list` shows no containers.

**Next (not done):**
1. Redeploy, put URL + token in `backend/.env`, restart backend, run `analyze-audio` for
   "Bohemian Rhapsody Queen", one `/api/chat/stream` message, and the failure path (stopped endpoint /
   wrong token) — handoff acceptance 3 and 4.
2. Read the full licence text; record the conclusion here.
3. Pin exact versions (build used transformers 5.22.1, torch 2.15, fastapi 0.162) and the HF revision hash.
4. Optional: try an A10 (24 GB, ~44% cheaper) and the MOSS-Music bake-off (§6).

## 6. Model comparison (MOSS-Music vs Music Flamingo)
You asked whether a better music model exists. Summary of the evidence:
- **MOSS-Music-8B** (OpenMOSS, released 2026-05-01, **Apache 2.0**, ~9.1B, built on MOSS-Audio).
  Its README claims higher captioning scores than Music Flamingo (MusicCaps 4.53 vs 4.21; SDD 4.58
  vs 4.26) using a **GPT-5.4 judge**. This is **self-reported and "preliminary"**; no paper covers
  MOSS-Music itself.
- **The MOSS-Audio paper** (`2606.01802v1.pdf`, in this folder) is a *general* model (speech/sound/
  music) and has **no music-captioning evaluation**. Two relevant details:
  - §3.5: its music training captions are built partly from **Music Flamingo / Qwen3-Omni /
    Audio-Flamingo base captions** plus MIR tools (Chordino, BeatNet, madmom, Essentia, SongFormer).
    So it is partly distilled from Music-Flamingo-style output; a judge preferring it may partly
    reflect that.
  - Appendix Table 6: the MOSS **encoder is weaker than Qwen3-Omni's encoder on every music probe**
    (FMA 0.623 vs 0.660, GTZAN 0.788 vs 0.869, NSynth 0.712 vs 0.767, SongDesc 0.491 vs 0.505). Its
    strengths are speech/ASR/environmental sound. Encoder-level only; full-model music fine-tuning
    could change this.
- **Audio Flamingo Next:** scores below Music Flamingo in the MOSS README table; rejection stands.
- **Music Flamingo `2601`** checkpoint exists (`MusicFlamingoForConditionalGeneration`, 20-min cap,
  NVIDIA transformers fork mentioned). Not evaluated; same noncommercial licence.

**Decision:** ship Music Flamingo now. Optional later bake-off: MOSS-Music-8B-Instruct on ~5 songs,
judged by reading captions and by chord/tempo/key correctness on songs you know. Main reason to
switch would be the Apache 2.0 licence if Mycelen/Irene ever becomes commercial. Same
`{"caption": ...}` contract, so switching needs no backend change.

## 7. Known risks / not verified
- **Class name vs transformers version:** resolved — `AudioFlamingo3ForConditionalGeneration`
  works under `transformers 5.22.1` / `torch 2.15` (verified by a successful caption).
- **Versions are unpinned** (`>=` lower bounds only). Freeze exact versions (and the HF model
  revision hash, currently `main`) after the first successful run.
- **GPU size, cold start, latency, cost per request, five-parallel behaviour:** all unmeasured.
- **Timeout:** backend waits 90 s total. If cold start + inference exceeds that, I will report it
  rather than silently raising the number.
- **YouTube from cloud IPs** may block the *backend's* download before this endpoint is ever
  called (out of scope here; not moving downloads into Modal without asking).

## 8. Review checklist (for you)
- [x] Payment method added on Modal.
- [ ] You accept L40S as the starting GPU (cost vs A10) — fit on 24 GB is untested.
- [ ] 600 s warm window OK, or prefer shorter (cheaper) / 900 s (fewer cold starts).
- [ ] Read the sample caption in §9 / run your own songs: is this the style you want? (`PROMPT` in code)
- [ ] Backend end-to-end + failure path still to run (§5 "Next").
- [ ] Licence conclusion still to be written.

## 9. Results (measured 2026-11-02, L40S, 163 s test mp3 from the model card's dataset)
Wall-clock as seen by curl, including upload. Single runs, so treat as rough.

| Test | Result |
|---|---|
| No token | `401` (cold container: 79 s; first ever boot, includes cold volume reads) |
| Wrong token | `401`, `{"detail":"invalid or missing bearer token"}` |
| Garbage bytes | `422` "could not decode audio" (not a crash, not a 200) |
| Real song, **cold** | `200`, **49.5 s** total (boot + model load + inference) |
| Real song, **warm** | `200`, **18.3 s** |
| **5 at once** (1 warm container) | all `200`: 11.8, 23.4, 48.6, 48.7, 53.9 s |
| Caption | ~110–150 words, one paragraph, no markdown; sample genre/instrument/vocal detail was plausible, but tempo and key were not stated |

Reading: cold + inference is **inside the backend's 90 s timeout**, but with only ~35–40 s margin
(the very first boot took 79 s before inference even ran — a one-off or occasional slow cold start
would exceed 90 s, and the backend would just drop the caption).
Parallel behaviour: the warm container serialises (lock), extra requests start new containers
(~50 s each), so a burst of five costs up to five containers' idle windows.

**Not measured:** GPU memory use, whether an A10 fits, longer (5–10 min) tracks, accuracy of tempo/key
(the caption rarely states them), no-persistence check (by design the code writes only a temp file and
deletes it in `finally`; not independently inspected in a running container).

**Cost (rough, L40S $0.000542/s = ~$1.95/h; pricing page checked 2026-11-02):** one cold request ≈
50 s + 600 s idle ≈ **$0.36**; a warm follow-up ≈ $0.01 but resets the idle clock; a 5-song burst
≈ up to $1.8. Testing this session ≈ a couple of dollars. Free credit: $30/month (Starter).
Licence: **not yet read** (NVIDIA OneWay Noncommercial; see §2).
