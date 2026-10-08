# API-credits storefront image. Trimmed from the VM storefront's
# Dockerfile: credit deals have no network provisioning, so none of the
# zerotier / NET_ADMIN / sudo machinery is needed. Serves the
# `apicredits-storefront` console script.
#
# --platform=linux/amd64 is intentional: production targets x86_64, and
# alkahest_py's wheel is resolved for that platform.

ARG PYTHON_VERSION=3.13

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

# No UV_COMPILE_BYTECODE: builds under x86 emulation where uv's
# bytecode-compile workers deadlock under Rosetta sporadically.
ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

RUN apt-get update && apt-get install -y --no-install-recommends git g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The lock is used as committed: the project's pyproject and lock sit at the
# same depth below /repo as below the repository root, so the lock's relative
# wheelhouse path resolves to /repo/.dist. uv_project.py derives the internal
# packages from the lock and reinstalls them, so a cached build of a
# same-version wheel is never reused.
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/apicredits/storefront/pyproject.toml domains/apicredits/storefront/uv.lock /repo/domains/apicredits/storefront/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

ARG GAR_STG_READER_KEY=""
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/apicredits/storefront -- --no-dev --no-install-project

# The storefront itself is installed from its staged wheel at the version its
# pyproject declares; the runtime image never receives repository source.
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/apicredits/storefront

# Stage 2: runtime
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS runtime

ENV UV_HTTP_RETRIES=10
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    useradd -m -s /bin/sh appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
WORKDIR /app

COPY --chown=appuser:appuser --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"
# Dynaconf config layering looks under $XDG_CONFIG_HOME/arkhai/; the
# operator's TOML is bind-mounted at /etc/arkhai/storefront.toml.
ENV XDG_CONFIG_HOME="/etc"



ARG PORT=8000
ENV PORT=${PORT}
EXPOSE ${PORT}

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["apicredits-storefront", "serve", "--host", "0.0.0.0", "--port", "8000"]
