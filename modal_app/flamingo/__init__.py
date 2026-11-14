"""Music Flamingo captioning service: engines, HTTP layer, shared helpers.

common.py        light shared code (prompt, caption cleanup, audio decoding)
hf_engine.py     baseline engine: Hugging Face transformers (needs torch)
vllm_engine.py   optimised engine: vLLM (needs vllm; GPU Linux only)
api.py           FastAPI app: auth, validation, timings (no GPU needed)

Each engine imports its heavy libraries at the top of its own file. Nothing here is imported on a
laptop except common.py and api.py (see music_flamingo.py, `image.imports()`).
"""
