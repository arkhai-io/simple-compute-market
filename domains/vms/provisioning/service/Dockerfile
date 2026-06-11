ARG PYTHON_VERSION=3.12

# Pin to linux/amd64 — ansible-galaxy collection install hits a SIGILL
# (illegal instruction) on native arm64 Podman, but runs fine under
# the same x86_64 emulation the storefront image already uses.
# Matches `platform: linux/amd64` in docker-compose.yml.

# Stage 1: Install Python deps and Ansible collections
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

# No UV_COMPILE_BYTECODE here: this image builds under x86 emulation
# (see the --platform pin) and uv's post-install bytecode-compile
# python workers deadlock under Rosetta sporadically — a wedged build,
# not a slow one. Cold starts pay a small first-import cost instead.
ENV UV_LINK_MODE=copy
# PyPI intermittently serves 5xx even for index lookups that should
# 404 (internal package names resolved from /dist); back off through
# the flap instead of failing the build after the default 3 tries.
ENV UV_HTTP_RETRIES=10

# UID/GID of the in-container `appuser`. Override at build time to match
# the host user that bind-mounts SSH keys / data dirs into the container
# — without alignment, mode-0600 keys mounted from a host user with a
# different UID become unreadable. Defaults preserve the historical
# uid=1000 image.
ARG APPUSER_UID=1000
ARG APPUSER_GID=1000

# psutil falls back to a source build on platforms without a prebuilt
# wheel (e.g. aarch64 cpython 3.13); needs a C toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid ${APPUSER_GID} appuser && \
    useradd --create-home --uid ${APPUSER_UID} --gid ${APPUSER_GID} --shell /bin/bash appuser
WORKDIR /app
RUN chown appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser domains/vms/provisioning/iac/ansible/requirements.yml /tmp/requirements.yml
# Keep Ansible in its own venv so the Galaxy collection layer does not depend
# on the application venv, local wheels, or arkhai-vms-provisioning source.
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=${APPUSER_UID} \
    uv venv /home/appuser/ansible-venv && \
    uv pip install --python /home/appuser/ansible-venv/bin/python 'ansible-core>=2.17,<2.20'
# Galaxy's API endpoint frequently returns truncated responses on the
# larger community.general tarball (~40MB). ansible-galaxy's downloader
# has no retry on IncompleteRead, so we pre-fetch each collection with
# curl --retry --retry-all-errors, then install from local files. The timeout
# and speed guards make zero-throughput connections fail and retry instead of
# hanging the whole image build.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
USER appuser
RUN mkdir -p /tmp/galaxy-tarballs && \
    for col in \
        "community-general-4.8.7" \
        "community-docker-2.7.2" \
        "community-crypto-2.5.0" \
    ; do \
        curl --retry 8 --retry-all-errors --retry-delay 5 \
            --connect-timeout 20 --max-time 180 \
            --speed-time 30 --speed-limit 1024 \
            -fSL \
            "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts/${col}.tar.gz" \
            -o "/tmp/galaxy-tarballs/${col}.tar.gz" \
            || (echo "Failed to fetch ${col}.tar.gz" && exit 1); \
    done && \
    /home/appuser/ansible-venv/bin/ansible-galaxy collection install \
        /tmp/galaxy-tarballs/community-crypto-2.5.0.tar.gz \
        /tmp/galaxy-tarballs/community-docker-2.7.2.tar.gz \
        /tmp/galaxy-tarballs/community-general-4.8.7.tar.gz

# Copy pre-built internal wheels (built by make dist before docker build).
# arkhai-core-storefront-client and other internal packages are resolved from here.
COPY --chown=appuser:appuser .dist/ /dist/

COPY --chown=appuser:appuser domains/vms/provisioning/service/pyproject.toml ./
COPY --chown=appuser:appuser domains/vms/provisioning/service/src ./src
# --refresh-package the internal wheels: they are rebuilt into /dist on
# every `make dist` without a version bump, so the uv cache mount would
# otherwise pin a stale copy from an earlier build.
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=${APPUSER_UID} \
    uv sync --no-dev --no-install-project --find-links /dist \
        --refresh-package arkhai-core-storefront-client

# Stage 2: Runtime
FROM --platform=linux/amd64 python:${PYTHON_VERSION}-slim AS runtime

# ARGs from build args; default 1000 (see explanation in builder stage).
ARG APPUSER_UID=1000
ARG APPUSER_GID=1000

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client sshpass && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid ${APPUSER_GID} appuser && \
    useradd --create-home --uid ${APPUSER_UID} --gid ${APPUSER_GID} --shell /bin/bash appuser
WORKDIR /app
RUN chown appuser:appuser /app

COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder --chown=appuser:appuser /home/appuser/ansible-venv /home/appuser/ansible-venv
COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /home/appuser/.ansible /home/appuser/.ansible

RUN mkdir -p /app/data
COPY --chown=appuser:appuser domains/vms/provisioning/service/src ./src
COPY --chown=appuser:appuser domains/vms/provisioning/iac /opt/domains/vms/provisioning/iac

ENV PATH="/home/appuser/ansible-venv/bin:/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src

# ---------------------------------------------------------------------------
# Activate the docker profile so config/config-docker.yml is loaded.
# This supplies the IaC paths and ansible.cfg location for containerised runs.
# In Kubernetes the Deployment overrides these to ACTIVE_PROFILES=production,
# which loads the ConfigMap-mounted config-production.yml instead.
# ---------------------------------------------------------------------------
ENV ACTIVE_PROFILES="docker"
ENV CONFIG_DIRECTORY="/app/src/config"

USER appuser

EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
