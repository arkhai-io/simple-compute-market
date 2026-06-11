ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
# --platform=linux/amd64 is intentional: production targets Linux x86_64.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
# PyPI intermittently serves 5xx even for index lookups that should
# 404 (internal package names resolved from /dist); back off through
# the flap instead of failing the build after the default 3 tries.
ENV UV_HTTP_RETRIES=10

WORKDIR /app

# Build context is the repo root (see Makefile): internal wheels
# (arkhai-kit-identity) resolve from /.dist via --find-links, and
# --no-sources ignores the pyproject's editable workspace paths, which
# exist for local dev only and cannot resolve inside the image.
COPY .dist/ /.dist/
COPY core/registry/src ./src
COPY core/registry/alembic ./alembic
COPY core/registry/filter-spec.yaml ./
COPY core/registry/pyproject.toml core/registry/uv.lock ./
# Normalize the lock's find-links registry path to the in-image wheel dir
# (uv records it relative to the repo, which cannot normalize from /app).
RUN sed -E -i 's|registry = "[^"]*\.dist"|registry = "/.dist"|' uv.lock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-sources --no-dev --no-install-project --find-links /.dist

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    chown appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src
COPY --from=builder --chown=appuser:appuser /app/alembic ./alembic
COPY --from=builder --chown=appuser:appuser /app/filter-spec.yaml ./
ENV PATH="/app/.venv/bin:$PATH"
USER appuser

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

ENV ENABLE_HEALTH_CHECKS=false HEALTH_CHECK_INTERVAL=60 ENDPOINT_CHECK_TIMEOUT=10 HEARTBEAT_TTL_SECS=60

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
