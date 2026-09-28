ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
# --platform=linux/amd64 is intentional: production targets Linux x86_64.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
# PyPI intermittently serves 5xx even for index lookups that should
# 404 (internal package names resolved from /dist); back off through
# the flap instead of failing the build after the default 3 tries.
# Cap each request: a wedged connection (podman's gvproxy can leave a
# socket ESTABLISHED with no data and no RST) must time out for the
# retries to fire — without this uv blocks indefinitely at 0% CPU.
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

WORKDIR /app

COPY core/registry/src ./src
COPY core/registry/alembic ./alembic
COPY core/registry/filter-spec.yaml ./
COPY domains/apicredits/registry/filter-spec.yaml ./filter-spec-apicredits.yaml
# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY core/registry/pyproject.toml core/registry/uv.lock /repo/core/registry/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/core/registry -- --no-dev --no-install-project

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    mkdir -p /app/data && \
    chown appuser:appuser /app /app/data

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src
COPY --from=builder --chown=appuser:appuser /app/alembic ./alembic
COPY --from=builder --chown=appuser:appuser /app/filter-spec.yaml ./
COPY --from=builder --chown=appuser:appuser /app/filter-spec-apicredits.yaml ./
ENV PATH="/app/.venv/bin:$PATH"
USER appuser

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

ENV ENABLE_HEALTH_CHECKS=false HEALTH_CHECK_INTERVAL=60 ENDPOINT_CHECK_TIMEOUT=10 HEARTBEAT_TTL_SECS=60

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "core_registry.main:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8080"]
