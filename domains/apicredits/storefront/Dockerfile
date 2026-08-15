# API-credits storefront image. Trimmed from the VM storefront's
# Dockerfile: credit deals have no network provisioning, so none of the
# zerotier / NET_ADMIN / sudo machinery is needed. Serves the
# `apicredits-storefront` console script.
#
# --platform=linux/amd64 is intentional: production targets x86_64, and
# alkahest_py's wheel is resolved for that platform.

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# No UV_COMPILE_BYTECODE: builds under x86 emulation where uv's
# bytecode-compile workers deadlock under Rosetta sporadically.
ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=10

RUN apt-get update && apt-get install -y --no-install-recommends git g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY .dist/ /.dist/
COPY domains/apicredits/storefront/pyproject.toml domains/apicredits/storefront/uv.lock ./
RUN sed -E -i 's|registry = "[^"]*\.dist"|registry = "/.dist"|' uv.lock || true

ARG GAR_STG_READER_KEY=""
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    uv sync --no-sources --no-dev --no-install-project --find-links /.dist \
        --refresh-package arkhai-core \
        --refresh-package arkhai-core-storefront \
        --refresh-package arkhai-core-registry-client \
        --refresh-package arkhai-kit-policy \
        --refresh-package arkhai-kit-settlement-runtime \
        --refresh-package arkhai-kit-alkahest \
        --refresh-package arkhai-kit-identity \
        --refresh-package arkhai-kit-config \
        --refresh-package arkhai-apicredits-domain \
        --refresh-package arkhai-kit-site-client

# Install the storefront distribution itself from the staged wheel. The
# runtime image never receives repository source, a project checkout, or an
# editable path that could bypass the package boundary exercised by release.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv/bin/python --no-deps --find-links /.dist \
        --reinstall arkhai-apicredits-storefront==0.2.0

# Stage 2: runtime
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ENV UV_HTTP_RETRIES=10
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    useradd -m -s /bin/sh appuser && mkdir -p /app && chown appuser /app
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
