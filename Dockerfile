FROM python:3.12-slim

WORKDIR /app

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency specifications
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code
COPY src/ src/
COPY app/ app/
COPY data/ data/
COPY .env.example .env

# Install project in editable mode
RUN uv pip install -e .

EXPOSE 8501

ENTRYPOINT ["uv", "run", "streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
