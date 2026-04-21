ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Workspace dependency: pyproject.toml references ../service via
# [tool.uv.sources], so the service package must be present at the
# parent-of-/app path (resolved as /service inside the image) before uv sync.
COPY service /service
COPY integration-tests/src ./src
COPY integration-tests/tests ./tests
COPY integration-tests/pyproject.toml integration-tests/uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Stage 2: Lean runtime image
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/tests ./tests
COPY --from=builder /service /service
COPY integration-tests/config ./config
COPY integration-tests/conftest.py .
COPY integration-tests/pyproject.toml .
COPY integration-tests/settings.toml .

ENV PATH="/app/.venv/bin:$PATH"

ENV ACTIVE_PROFILES="docker"
ENV CONFIG_DIRECTORY="/app/config/"

CMD .venv/bin/pytest 