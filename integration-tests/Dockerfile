ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# psutil 5.9.8 (transitive via fastapi-utils) has no cp313 aarch64
# wheel and falls back to a source build; needs a C toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built wheels from the monorepo .dist/ directory.
# These are built on the host by `make dist` before `docker build`.
# The Dockerfile is built from the monorepo root:
#   cd .. && docker build -t arkhai:integration-tests -f integration-tests/Dockerfile .
COPY .dist/ /dist/

COPY integration-tests/src ./src
COPY integration-tests/tests ./tests
COPY integration-tests/pyproject.toml ./

# --refresh-package the monorepo workspace wheels: they are rebuilt into
# .dist/ without a version bump, so a cached same-version wheel in the uv
# cache mount would otherwise shadow fresh content (e.g. a arkhai-kit-policy
# 0.1.0 missing a newly-added module). Third-party deps still hit the cache.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --find-links /dist \
        --refresh-package arkhai-vms-buyer \
        --refresh-package arkhai-kit-policy \
        --refresh-package arkhai-vms-storefront \
        --refresh-package arkhai-vms-provisioning \
        --refresh-package arkhai-core-storefront-client \
        --refresh-package arkhai-core-registry-client

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
