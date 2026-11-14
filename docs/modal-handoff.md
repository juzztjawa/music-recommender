# Modal handoff — host Music Flamingo for audio captioning

For the agent taking over the **audio-captioning service**. Read this file, then the files in §8.
You build and deploy a small GPU web endpoint on **Modal** that turns an audio file into a text
caption, and wire it into the existing backend by configuration only.

## 1. Why this exists
Orchestra recommends music by first understanding *why* the user likes their input songs. For each
input song the backend downloads its audio from YouTube (`yt-dlp`) and asks an audio-understanding
model to describe it (instrumentation, tempo, energy, mood, progression). That text — the
**caption** — is handed to the supervisor agent, which writes search hypotheses from it
(requirements FR-3.2, FR-3.4; architecture §4, §9).

**Today the model is not hosted**, so `MUSIC_FLAMINGO_ENDPOINT_URL` is empty and every caption is
`null`. The backend now skips the YouTube download entirely when that setting is empty (commit
`27be6cf`), so audio contributes nothing and the UI's "Listening to the audio" line is only a label.
Your job makes that line true.

## 2. Decisions already made (do not reopen)
Source: `design/architecture.md` §4 and §9 (private, git-ignored; condensed here).

| Decision | Detail |
|---|---|
| Model | **Music Flamingo 7B**, checkpoint `nvidia/music-flamingo-hf`. A music specialist; hands-on test of its HF Space gave rich captions (chords, structure, instrumentation, mood), not just a genre tag. |
| Host | **Modal** serverless GPU, scale-to-zero. **RunPod Serverless is the fallback** if Modal proves unworkable. No always-on GPU. |
| Rejected | **Audio Flamingo Next (AF-Next)**: same size but a generalist (speech/sound/music); its edge rests on an unreleased, NVIDIA-internal benchmark; Music Flamingo has a real MusicCaps score (8.8) and AF-Next reports none. Swapping later is cheap (same size, licence family, hosting plan). |
| Audio scope | **Input songs only**, never retrieval candidates (FR-3.4). |
| Data handling | **Process and discard.** Audio is never stored (architecture §17). The service must not persist uploads. |
| Failure | Best-effort. If the endpoint is down or slow the backend degrades gracefully (FR-3.3): the caption is null and recommendations still run. |

## 3. The contract your service must satisfy (set by the existing client)
The backend side is already built and unit-tested with mocks: `backend/app/clients/music_flamingo.py`.
It has **never called a real endpoint**. The contract is ours, so it can be extended if you change
the backend in the same step (see §9).

**Request** — `POST {MUSIC_FLAMINGO_ENDPOINT_URL}`
- `multipart/form-data` with one file field named **`audio`**, content type `audio/mpeg`.
- Optional header `Authorization: Bearer {MUSIC_FLAMINGO_API_KEY}` (sent only when that key is set).
  Require it on the service.
- The file is an **mp3, 192 kbps**, produced by ffmpeg from the YouTube audio of one track. The
  backend caps the source at ~29 minutes (= the endpoint's 40 MB upload limit at 192 kbps); typical tracks are 3–6 minutes (≈ 3–10 MB).

**Response** — `200` with JSON `{"caption": "<non-empty text>"}`.
- Anything non-2xx raises on the client (`raise_for_status`).
- A missing or empty `caption` is treated as a failure (`RuntimeError`).
- Unauthorized should be `401`; unreadable audio `4xx`; do not return a `200` with an error body.

**Timeout** — the client waits `MUSIC_FLAMINGO_TIMEOUT_SECONDS` (default **600 s**) for the whole
call: cold start plus inference. Measured cold starts ran 73-179 s (most of the slow one was waiting for
Modal to find a free L40S), and a warm caption takes about 10-13 s. Modal answers a web request that
runs longer than ~150 s with a 303 redirect to a result URL, so the client follows redirects.

**Caption content** — it goes into an LLM's context for up to five songs per message, so keep it to
a few hundred tokens of descriptive prose: instrumentation, tempo, energy, dynamics, mood,
progression, ambience (the FR-3.2 list). No markdown, no preamble ("This audio…" is fine).

## 4. Constraints and risks to design around
- **Cold start vs. latency budget.** The requirements target ~60 s per recommendation (NFR-1), and a
  7B multimodal model cold-starts in ~20–45 s on serverless GPUs. Architecture §9 says to tune the
  container's idle window so it stays warm **~10–15 minutes** after the last request (a user's
  session hits it several times) instead of scaling to zero immediately. Needs empirical measurement.
- **Several songs per message, in parallel.** The supervisor can analyse up to five songs at once;
  the endpoint should accept concurrent requests (batching or multiple containers) without five
  cold starts.
- **Licence.** Checkpoints ship under NVIDIA's **OneWay Noncommercial** licence, plus Qwen2.5's terms
  underneath. The project is non-commercial, so it very likely clears, but **read the licence text
  and record the conclusion** in your docs before real testers use it (architecture §9 item 1).
- **Cost.** Target is a few dollars a month for a 5–10 user cohort. Document cost per request
  (cold and warm) and the idle-window trade-off.
- **GPU size is unverified.** A 7B model in bf16 likely needs a 24 GB-class GPU, but confirm against
  the model card and measured memory; do not trust this estimate.
- **Modal API names change.** Check the current Modal docs (concurrency, scale-down window, volumes,
  web endpoints, secrets) instead of relying on memory.
- **YouTube from cloud IPs.** Not your service, but note it: the download runs in the *backend*, and
  YouTube often blocks datacenter IPs, so in production the download may fail before your endpoint is
  ever called. Do not move downloading into Modal without asking the owner.

## 5. Suggested layout and deliverables
Keep it **outside `backend/`** so it is not shipped in the backend's Docker image:

```
modal_app/
  music_flamingo.py   # Modal app + web endpoint implementing §3
  README.md           # deploy + test steps, measured latencies, licence note, cost
  (pinned deps)       # e.g. requirements.txt or an inline image definition
```
- Model weights cached in a **Modal Volume** (not re-downloaded per cold start).
- Secrets (bearer token, Hugging Face token if the repo is gated) in **Modal secrets**; never in the
  repo, never in logs.
- Pin versions (model revision, transformers, torch) and say which.
- Return a short, deterministic-ish caption; document the prompt used to elicit it so it can be tuned.

## 6. Acceptance criteria
1. `curl -F audio=@song.mp3 -H "Authorization: Bearer …" <url>` returns `{"caption": "…"}` for a real
   song; a request without the token gets `401`; garbage input gets a `4xx`, not a crash or a `200`.
2. **Measured and written down:** cold-start latency, warm latency, and a five-songs-at-once test.
3. Backend end to end: put the URL/key in `backend/.env`, restart, then
   `POST /api/discovery/analyze-audio {"query": "Bohemian Rhapsody Queen"}` (needs a JWT; see
   `SETUP.md`) returns a real `caption`; then one chat message through `/api/chat/stream` shows the
   captions in the `analyze_audio` tool results (MLflow at http://localhost:5000, or the
   `interaction_events` table).
4. Failure path: with the endpoint stopped or a wrong token, `analyze-audio` returns `error` set and a
   full chat run still completes.
5. No audio persisted (describe how you checked); licence conclusion and cost per request in the README.
6. `SETUP.md` updated (new env values, how to deploy/redeploy, troubleshooting) with a changelog
   line.

## 7. Rules
- Work in `modal_app/` and `docs/`. The backend should need **configuration only**
  (`MUSIC_FLAMINGO_ENDPOINT_URL`, `MUSIC_FLAMINGO_API_KEY`, `MUSIC_FLAMINGO_TIMEOUT_SECONDS`). If the
  contract must change, write the request in `docs/backend-requests.md` and tell the owner; do not
  edit backend logic yourself.
- Do not commit unless the owner asks. Never put secrets in the repo or paste them into chat.
- **The owner must do the account steps** you cannot: create a Modal account and run
  `modal token new`. Ask once, clearly, then continue.
- The owner reviews markdown, not code: finish with `modal_app/README.md` covering what, why,
  trade-offs, what was verified vs. not, and a review checklist.

## 8. What to read
Code (read these first):
- `backend/app/clients/music_flamingo.py` — the client; defines the contract in §3.
- `backend/app/agents/audio.py` — download → caption → discard; never raises; skips when unconfigured.
- `backend/app/tools/orchestrator.py` (`analyze_audio`) — how the supervisor calls it.
- `backend/app/clients/youtube_audio.py` — how the mp3 is produced (yt-dlp + ffmpeg, duration cap derived from the 40 MB upload limit).
- `backend/app/config.py` (search `music_flamingo`) and `backend/.env.example`.
- `backend/tests/agents/test_audio.py` — the behaviour the backend guarantees.

Docs:
- `design/architecture.md` §2 (audio agent), §4 (model choice), §9 item 1 (cold start, licence, why not
  AF-Next). **Private and git-ignored but present on this machine.**
- `design/PROJECT_STATUS.md` §8 (Phase 5, the audio agent) and §9 (deployment intent).
- `design/srs-02.md` FR-3.2–3.4, FR-7.3; `design/srs-03.md` NFR-1 (latency), NFR-3 (graceful degradation).
- `docs/02-discovery-pipeline.md` (how the supervisor uses audio), `docs/06-risks-and-open-items.md`,
  `SETUP.md` (§4 config, §6 seeing what a run did, troubleshooting).

## 9. State of verification (be skeptical)
- The client and agent are tested with **mocked** HTTP/download only; nothing has ever called a real
  Music Flamingo endpoint, and no Modal code exists in this repo (the `modal` mentions in
  `config.py`/`music_flamingo.py` are comments).
- The earlier "open call" wording in `config.py` is stale: Modal is the decision.
- The audio caption has never influenced a real recommendation, so how much it improves quality is
  unknown; once it works, a before/after comparison on a few songs would be a useful addition.
- The whole supervisor flow is also unproven against the real LLM; if a run misbehaves for reasons that
  are not about audio, that is a separate track (see `docs/02-discovery-pipeline.md`).
