# syntax=docker/dockerfile:1.4
ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.10.0

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# TODO: Pin with SHA256 digest for production: FROM python:3.13-slim@sha256:...
FROM python:${PYTHON_VERSION}-slim

# ── System deps (SSH for Ansible) ────────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client sshpass && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/* /var/tmp/*

COPY --from=uv /uv /uvx /bin/

# Create non-root user with explicit UID/GID for security
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

WORKDIR /app
RUN chown appuser:appuser /app

USER appuser

# ── Python deps ──────────────────────────────────────────────────────
COPY --chown=appuser:appuser async-provisioning-service/pyproject.toml async-provisioning-service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Ansible collections ─────────────────────────────────────────────
COPY --chown=appuser:appuser compute-provisioning-iac/ansible/requirements.yml /tmp/requirements.yml
RUN uv pip install ansible-core && \
    uv run ansible-galaxy collection install -r /tmp/requirements.yml && \
    rm -rf /tmp/* /home/appuser/.cache && \
    find /usr/local/lib/python${PYTHON_VERSION:-3.13} -name "*.pyc" -delete && \
    find /usr/local/lib/python${PYTHON_VERSION:-3.13} -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ── Application code ────────────────────────────────────────────────
COPY --chown=appuser:appuser async-provisioning-service/src ./src
COPY --chown=appuser:appuser async-provisioning-service/start.sh ./

# ── IaC submodule (baked into image; can be overridden at runtime) ──
COPY --chown=appuser:appuser compute-provisioning-iac ./compute-provisioning-iac

# ── Environment ─────────────────────────────────────────────────────
ENV PYTHONPATH=/app/src
ENV ANSIBLE_CONFIG=/app/compute-provisioning-iac/ansible/ansible.cfg

# ── Runtime Configuration (provide at runtime via -e or docker-compose) ──
# SECURITY: Sensitive values should be provided at runtime
# DO NOT hardcode credentials in this file or commit them to version control

# Service configuration
ENV HOST=0.0.0.0
ENV PORT=8081
ENV LOG_LEVEL=info

# Database configuration (provide at runtime)
# Use PostgreSQL for production: postgresql+psycopg2://user:pass@host:5432/db
# Use SQLite for development: sqlite:///provisioning.db
ENV DATABASE_URL=""

# Redis queue configuration (provide at runtime)
ENV REDIS_URL=""
ENV REDIS_QUEUE_NAME=provisioning_jobs

# Ansible configuration
ENV ANSIBLE_TIMEOUT_SECONDS=1800
ENV ANSIBLE_BECOME_PASS=""
ENV DEFAULT_VM_HOST=""

# Optional: Override default paths (auto-detected if not set)
ENV PROVISIONING_REPO_ROOT=""
ENV PLAYBOOK_PATH=""
ENV INVENTORY_PATH=""

# FRP Server Configuration (provide at runtime)
ENV FRP_SERVER_ADDR=""
ENV FRP_DOMAIN=""
ENV FRP_DASHBOARD_PASSWORD=""

# Authentication
ENV ENABLE_AUTH=false
ENV REGISTRY_URL=""
ENV REGISTRY_CACHE_TTL_SECONDS=300
ENV REGISTRY_CACHE_MAX_SIZE=256

# Admin
ENV ADMIN_SECRET=""

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]

CMD ["sh", "start.sh"]
