ARG PYTHON_VERSION=3.13

# Stage 1: Install dependencies into .venv
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

# No UV_COMPILE_BYTECODE here: this image builds under x86 emulation
# and uv's post-install bytecode-compile python workers deadlock under
# Rosetta sporadically — a wedged build, not a slow one. Cold starts
# pay a small first-import cost instead.
ENV UV_LINK_MODE=copy
# PyPI intermittently serves 5xx even for index lookups that should
# 404 (internal package names resolved from /dist); back off through
# the flap instead of failing the build after the default 3 tries.
ENV UV_HTTP_RETRIES=10

# psutil 5.9.8 (transitive via fastapi-utils) has no cp313 aarch64
# wheel and falls back to a source build; needs a C toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built wheels from the monorepo .dist/ directory.
# These are built on the host by `make dist` before `docker build`.
# The Dockerfile is built from the monorepo root:
#   cd .. && docker build -t arkhai:e2e-tests -f e2e-tests/Dockerfile .
COPY .dist/ /dist/

COPY e2e-tests/src ./src
COPY e2e-tests/tests ./tests
COPY e2e-tests/pyproject.toml ./

# --refresh-package the monorepo workspace wheels: they are rebuilt into
# .dist/ without a version bump, so a cached same-version wheel in the uv
# cache mount would otherwise shadow fresh content (e.g. a arkhai-kit-policy
# 0.1.0 missing a newly-added module). Third-party deps still hit the cache.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --find-links /dist \
        --refresh-package arkhai-core \
        --refresh-package arkhai-core-buyer \
        --refresh-package arkhai-core-storefront \
        --refresh-package arkhai-core-site \
        --refresh-package arkhai-apitokens-service \
        --refresh-package arkhai-apitokens-storefront \
        --refresh-package arkhai-vms-buyer \
        --refresh-package arkhai-apitokens-buyer \
        --refresh-package arkhai-kit-policy \
        --refresh-package arkhai-vms-storefront \
        --refresh-package arkhai-vms-provisioning-client \
        --refresh-package arkhai-core-storefront-client \
        --refresh-package arkhai-kit-alkahest \
        --refresh-package arkhai-kit-identity \
        --refresh-package arkhai-kit-config \
        --refresh-package arkhai-core-registry-client

# Stage 2: Lean runtime image
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/tests ./tests
COPY e2e-tests/config ./config
COPY e2e-tests/conftest.py .
COPY e2e-tests/pyproject.toml .
COPY e2e-tests/settings.toml .

ENV PATH="/app/.venv/bin:$PATH"

ENV ACTIVE_PROFILES="docker"
ENV CONFIG_DIRECTORY="/app/config/"

CMD .venv/bin/pytest
