# Environment for the Music Flamingo endpoint. Code is NOT baked in: Modal mounts engines.py/api.py
# at deploy time, so editing code never rebuilds this (large) image. Only pyproject.toml/uv.lock do.
#
# Build context = modal_app/ (see .dockerignore). Install is exactly the `serve` group of uv.lock.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# ffmpeg + libsndfile: audio decode.  build-essential (gcc): Triton / torch.compile build small stubs at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

WORKDIR /opt/serve
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --only-group serve

ENV PATH="/opt/serve/.venv/bin:${PATH}"
