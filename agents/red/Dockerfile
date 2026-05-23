# syntax=docker/dockerfile:1

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install dependencies only (cache-friendly layer)
COPY pyproject.toml uv.lock ./
COPY agents/red/pyproject.toml agents/red/pyproject.toml
COPY agents/red/README.md agents/red/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package red

COPY agents/red/ agents/red/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package red

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/agents/red

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
