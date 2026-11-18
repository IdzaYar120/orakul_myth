FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# 1. Dependencies only (cached layer while pyproject/uv.lock are unchanged)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 2. Project code (README.md is required by pyproject `readme`)
COPY README.md ./
COPY src/ src/
COPY app/ app/
COPY data/ data/
RUN uv sync --frozen --no-dev

# Generated storage lives in volumes (see docker-compose.yml)
RUN mkdir -p /app/storage /app/index
ENV DB_PATH=/app/storage/delphi.db \
    INDEX_DIR=/app/index

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

# Settings come from environment variables / env_file, never baked into the image.
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
