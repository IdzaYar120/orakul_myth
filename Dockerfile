FROM python:3.12-slim

WORKDIR /app

# Встановлення uv для швидкого керування пакетами
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Копіювання конфігурацій залежностей
COPY pyproject.toml uv.lock* ./

# Встановлення залежностей
RUN uv sync --frozen --no-install-project --no-dev

# Копіювання коду проєкту
COPY src/ src/
COPY app/ app/
COPY data/ data/
COPY .env.example .env

# Встановлення самого проєкту в режимі editable
RUN uv pip install -e .

EXPOSE 8501

ENTRYPOINT ["uv", "run", "streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
