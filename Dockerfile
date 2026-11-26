# syntax=docker/dockerfile:1
# Two images from one Dockerfile:
#   docker build --target api  -t delphi-api  .   # public API: no ML stack, no Streamlit; the
#                                                 # oracle is forwarded to ORACLE_BACKEND_URL
#   docker build --target full -t delphi-oracle . # everything: RAG oracle (Chroma, bge-m3),
#                                                 # Streamlit UI, ingest/eval CLI
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./

# ---------------------------------------------------------------- dependency layers (cached)
# The uv download cache lives in a BuildKit cache mount, not in the image layers.
FROM runtime AS deps-api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

FROM runtime AS deps-full
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra ml --extra ui

# ---------------------------------------------------------------- public API
FROM deps-api AS api
# README.md is required by pyproject `readme`
COPY README.md ./
COPY src/ src/
COPY data/ data/
# The encyclopedia/map database is public data: built into the image, read-only at runtime.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && mkdir -p /app/storage \
    && DB_PATH=/app/storage/delphi.db delphi seed
ENV DB_PATH=/app/storage/delphi.db \
    ORACLE_MODE=remote \
    ORACLE_WARMUP=false
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["delphi", "serve", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- full (oracle node, UI)
FROM deps-full AS full
COPY README.md ./
COPY src/ src/
COPY app/ app/
COPY data/ data/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml --extra ui
# Generated storage lives in volumes (see docker-compose.yml)
RUN mkdir -p /app/storage /app/index
ENV DB_PATH=/app/storage/delphi.db \
    INDEX_DIR=/app/index \
    HF_HOME=/app/hf_cache
EXPOSE 8501 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
# Settings come from environment variables / env_file, never baked into the image.
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
