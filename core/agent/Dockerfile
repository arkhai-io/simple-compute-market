# Stage 1: Dependency Downloading and building the wheel
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

FROM python:3.12-slim

#This installs the dependencies to a cache layer so they don't need to be redownloaded every docker build
#The output is a cache of the .venv folder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY packages/ ./packages/
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Stage 2: Lean runtime image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Copy the cached venv from builder
COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application code
COPY ./app .
COPY .env.sample .

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "core.agent.app.server:app", "--host", "0.0.0.0", "--port", "8080"]
