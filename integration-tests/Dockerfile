ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy the pre-built wheels from the monorepo .dist/ directory.
# These are built on the host by `make dist` before `docker build`.
# The Dockerfile is built from the monorepo root:
#   cd .. && docker build -t arkhai:integration-tests -f integration-tests/Dockerfile .
COPY .dist/ /dist/

COPY integration-tests/src ./src
COPY integration-tests/tests ./tests
COPY integration-tests/pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --find-links /dist

# Stage 2: Lean runtime image
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/tests ./tests
COPY integration-tests/config ./config
COPY integration-tests/conftest.py .
COPY integration-tests/pyproject.toml .
COPY integration-tests/settings.toml .

ENV PATH="/app/.venv/bin:$PATH"

ENV ACTIVE_PROFILES="docker"
ENV CONFIG_DIRECTORY="/app/config/"

CMD .venv/bin/pytest
