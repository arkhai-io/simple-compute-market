ARG PYTHON_VERSION=3.13

# Stage 1: install the sample app + its middleware from the monorepo
# wheels. Built from the repo root so .dist/ is in context.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_LINK_MODE=copy
# Cap each request so a wedged connection (podman's gvproxy can leave a
# socket open with no data) times out and the retries fire, instead of
# uv hanging the build indefinitely at 0% CPU.
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

WORKDIR /app
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser && chown appuser:appuser /app
USER appuser

# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused.
COPY --chown=appuser:appuser .dist/ /repo/.dist/
COPY --chown=appuser:appuser scripts/uv_project.py /repo/scripts/uv_project.py
COPY --chown=appuser:appuser domains/apicredits/sample-app/pyproject.toml domains/apicredits/sample-app/uv.lock /repo/domains/apicredits/sample-app/
ENV UV_PROJECT_ENVIRONMENT=/home/appuser/.venv
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/apicredits/sample-app -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/apicredits/sample-app

# Stage 2: lean runtime.
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /home/appuser
COPY --from=builder --chown=appuser:appuser /home/appuser/.venv ./.venv
ENV PATH="/home/appuser/.venv/bin:$PATH"
USER appuser

ARG PORT=8085
ENV APICREDITS_SAMPLE_APP_PORT=${PORT}
EXPOSE ${PORT}

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8085/health')" || exit 1

CMD ["apicredits-sample-app"]
