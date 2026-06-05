# --platform=linux/amd64 is intentional: production targets Linux x86_64.
# Keep this pin in all FROM lines.

# Stage 1: Install Python dependencies using uv
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120

RUN apt-get update && apt-get install -y --no-install-recommends git g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built wheels from the monorepo .dist/ directory.
# These are built on the host by `make dist` before `docker build`.
COPY .dist/ /.dist/

COPY storefront/pyproject.toml storefront/uv.lock storefront/entrypoint.sh ./
COPY service/ ../service/
COPY policy/ ../policy/
# arkhai-storefront-client is a workspace path source in
# storefront/pyproject.toml (editable=true). The lock file pins it to
# editable+../storefront-client, so the source tree must be present
# at build time even though we also ship the prebuilt wheel in .dist/.
COPY storefront-client/ ../storefront-client/

# Pass the GCP service account JSON key from GitHub Actions secrets to authenticate
# against GCP Artifact Registry for the alkahest-py private Python package.
ARG GAR_STG_READER_KEY=""
ARG INSTALL_RL_DEPS=false

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${GAR_STG_READER_KEY}" ]; then \
        export UV_INDEX_ALKAHEST_GAR_USERNAME="_json_key" && \
        export UV_INDEX_ALKAHEST_GAR_PASSWORD="$(echo "${GAR_STG_READER_KEY}" | tr -d '\n' | python3 -c 'import sys,json; print(json.dumps(json.loads(sys.stdin.read())))' 2>/dev/null || echo "${GAR_STG_READER_KEY}")"; \
    fi && \
    if [ "${INSTALL_RL_DEPS}" = "true" ]; then \
        uv sync --no-dev --no-install-project --extra rl --find-links /.dist \
            --refresh-package arkhai-registry-client \
            --refresh-package arkhai-storefront-client \
            --refresh-package market-service \
            --refresh-package market-policy \
            --refresh-package provisioning-service; \
    else \
        uv sync --no-dev --no-install-project --find-links /.dist \
            --refresh-package arkhai-registry-client \
            --refresh-package arkhai-storefront-client \
            --refresh-package market-service \
            --refresh-package market-policy \
            --refresh-package provisioning-service; \
    fi

# Stage 2: Lean runtime image
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg iproute2 kmod sudo git && \
    curl -s https://install.zerotier.com | bash && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/lib/zerotier-one && \
    printf '{\n  "settings": {\n    "allowManagementFrom": [ "127.0.0.1", "::1" ]\n  }\n}\n' \
      > /var/lib/zerotier-one/local.conf && \
    rm -f /var/lib/zerotier-one/identity.public /var/lib/zerotier-one/identity.secret && \
    useradd -m -s /bin/sh appuser && \
    echo 'appuser ALL=(root) NOPASSWD: /usr/sbin/zerotier-one, /usr/sbin/zerotier-cli' \
      > /etc/sudoers.d/appuser && \
    chmod 0440 /etc/sudoers.d/appuser && \
    mkdir -p /app && \
    chown appuser /app

USER appuser
WORKDIR /app

EXPOSE 9993/udp

COPY --chown=appuser:appuser --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"
# /app is the WORKDIR; domain/ is copied here. Console-script entry points
# don't inherit CWD on sys.path, so we set PYTHONPATH explicitly.
ENV PYTHONPATH="/app"
# Dynaconf-driven config layering looks for the storefront TOML under
# $XDG_CONFIG_HOME/arkhai/. Bind-mount the operator's TOML at
# /etc/arkhai/storefront.toml.
ENV XDG_CONFIG_HOME="/etc"

# Copy application code. The market_storefront package is shipped at
# /app/src/market_storefront so it's importable via the venv-installed
# package; the domain/ tree is copied in for compute-domain policy
# callables that the storefront's PolicyManager discovers at startup.
COPY --chown=appuser:appuser storefront/src ./src
COPY --chown=appuser:appuser storefront/scripts ./scripts
COPY --chown=appuser:appuser domain/ ./domain/
COPY --chown=appuser:appuser service/ ../service/
COPY --chown=appuser:appuser policy/ ../policy/

# Complete the two-phase uv install: deps were installed with
# --no-install-project in the builder stage (for layer caching);
# now install the project itself so the `market-storefront` console
# script is written to .venv/bin/.
# /.dist/ carries the internal wheels needed for --find-links resolution.
COPY --chown=appuser:appuser storefront/pyproject.toml storefront/uv.lock ./
COPY --chown=appuser:appuser storefront-client/ ../storefront-client/
# Copy wheels directly from the build context (not from the builder stage).
# Using --from=builder here would serve a cached /.dist that Docker baked at
# the last full builder rebuild, silently ignoring any make dist updates since.
# Sourcing from the build context means this layer invalidates whenever
# .dist/ changes on disk, which is exactly what we want.
COPY .dist/ /.dist/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --find-links /.dist \
        --refresh-package arkhai-registry-client \
        --refresh-package arkhai-storefront-client \
        --refresh-package market-service \
        --refresh-package market-policy \
        --refresh-package provisioning-service

ARG PORT=8080
ENV PORT=${PORT}
EXPOSE ${PORT}

COPY --chown=appuser:appuser storefront/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ARG MODEL_VERSION=""
ENV MODEL_VERSION=${MODEL_VERSION}

CMD ["./entrypoint.sh"]
