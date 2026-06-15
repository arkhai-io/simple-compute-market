ARG PYTHON_VERSION=3.13

# Stage 1: install deps into a venv. Built from the repo root (see the
# Makefile build-image target) so the internal wheels in .dist/ resolve.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy
# Internal package names resolve from /.dist; PyPI intermittently 5xxs on
# the index lookups that should 404, so back off through the flap.
ENV UV_HTTP_RETRIES=10

WORKDIR /app

COPY .dist/ /.dist/
COPY domains/apitokens/service/pyproject.toml domains/apitokens/service/uv.lock ./
# The lock records the find-links dir relative to the repo; point it at
# the in-image wheel dir (uv re-canonicalizes on every relock).
RUN sed -E -i 's|registry = "[^"]*\.dist"|registry = "/.dist"|' uv.lock || true

# Deps only — the app modules are copied in and run via --app-dir, the
# same way `make serve` / the tests run them (top-level main/config/...).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-sources --no-dev --no-install-project --find-links /.dist

# Stage 2: lean runtime.
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    mkdir -p /app/data && chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --chown=appuser:appuser domains/apitokens/service/src ./src
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
# Persist the SQLite DB on the named volume mounted at /app/data.
ENV APITOKENS_DATABASE_URL="sqlite:////app/data/apitokens.db"
USER appuser

ARG PORT=8082
ENV APITOKENS_PORT=${PORT}
EXPOSE ${PORT}

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8082/health')" || exit 1

CMD ["uvicorn", "main:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8082"]
