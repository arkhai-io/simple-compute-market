ARG PYTHON_VERSION=3.13

# Stage 1: Install Python deps and Ansible collections
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /app
RUN chown appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser provisioning-service/pyproject.toml provisioning-service/uv.lock ./
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser compute-provisioning-iac/ansible/requirements.yml /tmp/requirements.yml
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    uv pip install ansible-core && \
    uv run ansible-galaxy collection install -r /tmp/requirements.yml

# Stage 2: Runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client sshpass && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /app
RUN chown appuser:appuser /app

COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /home/appuser/.ansible /home/appuser/.ansible

RUN mkdir -p /app/data
COPY --chown=appuser:appuser provisioning-service/src ./src
COPY --chown=appuser:appuser compute-provisioning-iac /opt/compute-provisioning-iac

ENV PATH="/app/.venv/bin:$PATH"
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