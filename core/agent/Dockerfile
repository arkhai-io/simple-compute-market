# Stage 1: Dependency Downloading and building the wheel
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

FROM python:3.12-slim

#This installs the dependencies to a cache layer so they don't need to be redownloaded every docker build
#The output is a cache of the .venv folder
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY packages/ ./packages/
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Copy the cached venv from builder
COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application code
COPY ./app .
COPY ./scripts ./scripts
COPY .env.sample .

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

EXPOSE 8080

<<<<<<< HEAD:core/agent/Dockerfile
CMD ["uv", "run", "uvicorn", "core.agent.app.server:app", "--host", "0.0.0.0", "--port", "8080"]
=======
# This needs to be patched to a valid cmd. I was digging through the makefile for targets but it isn't clear what I should run.
# The contents of make serve-a2a are too complicated for a cmd.
# I could convert it to a shell script and run that but the functionality of the target appears to me like it should be part of the Python code.
CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
# CMD ["sleep", "infinity"]
>>>>>>> 7e79935 (feat(docker): update agent dockerfile and create docker-compose):agent/Dockerfile
