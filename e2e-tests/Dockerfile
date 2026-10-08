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
COPY .dist/ /.dist/
COPY scripts/uv_project.py /scripts/uv_project.py

COPY e2e-tests/src ./src
COPY e2e-tests/tests ./tests
# The lock travels with the manifest. Without it `uv sync` re-resolves every
# dependency from the index at build time, so the image's third-party
# versions were whatever PyPI happened to be serving -- which is how a
# greenlet release carrying only macOS and Windows wheels broke a build that
# had changed nothing. The committed lock pins a version with an sdist.
#
# Same pattern as `domains/apicredits/storefront/Dockerfile` and the other
# service images, including the registry rewrite below.
COPY e2e-tests/pyproject.toml e2e-tests/uv.lock ./

# The lock is used as committed: /app sits one level below /, as e2e-tests sits
# below the repository root, so the lock's relative wheelhouse path resolves to
# /.dist. uv_project.py derives the internal packages from the lock and
# reinstalls them, so a cached build of a same-version wheel is never reused.
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /scripts/uv_project.py image --project /app --

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
