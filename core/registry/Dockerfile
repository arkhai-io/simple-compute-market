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

# The two filter specifications a deployment names by path: the compute one,
# which the wheel also carries as the registry's default, and API credits'.
COPY core/registry/src/core_registry/filter-spec.yaml ./
COPY domains/apicredits/registry/filter-spec.yaml ./filter-spec-apicredits.yaml
# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused. The wheelhouse's digest
# (scripts/wheelhouse_digest.py) keys the install's cache.
ARG WHEELHOUSE_DIGEST
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY core/registry/pyproject.toml core/registry/uv.lock /repo/core/registry/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
# The project's own wheel installs the registry, its Alembic scripts, and its
# console scripts, the migration command among them.
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/core/registry -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/core/registry

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    mkdir -p /app/data && \
    chown appuser:appuser /app /app/data

# The digest of the wheelhouse this image installed, which loading a release
# candidate requires to be the digest of the wheelhouse it stores. Set before
# the cross-stage copies, which Podman could otherwise reuse from a build of
# another wheelhouse.
ARG WHEELHOUSE_DIGEST
LABEL org.arkhai.wheelhouse-digest="${WHEELHOUSE_DIGEST}"

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/filter-spec.yaml ./
COPY --from=builder --chown=appuser:appuser /app/filter-spec-apicredits.yaml ./
ENV PATH="/app/.venv/bin:$PATH"
USER appuser

# No ENV for the port: a process variable would override the PORT a profile env
# file states, and the settings default it to 8080 already.
ARG PORT=8080
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# The migration command runs before the application, which refuses a database
# it has not migrated. The Helm chart runs the command as an init container and
# the application alone; Compose states this command.
CMD ["sh", "-c", "registry-migrate && exec uvicorn core_registry.main:app --host 0.0.0.0 --port 8080"]
