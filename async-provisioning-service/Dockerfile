ARG PYTHON_VERSION=3.13

# Stage 1: Install Python deps and Ansible collections
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /app
RUN chown appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser async-provisioning-service/pyproject.toml async-provisioning-service/uv.lock ./
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser compute-provisioning-iac/ansible/requirements.yml /tmp/requirements.yml
RUN uv pip install ansible-core && \
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

COPY --chown=appuser:appuser async-provisioning-service/src ./src
COPY --chown=appuser:appuser async-provisioning-service/start.sh ./
COPY --chown=appuser:appuser compute-provisioning-iac ./compute-provisioning-iac

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
ENV ANSIBLE_CONFIG=/app/compute-provisioning-iac/ansible/ansible.cfg

# Service configuration
ENV HOST=0.0.0.0
ENV PORT=8081
ENV LOG_LEVEL=info

# Database configuration (set at runtime)
# PostgreSQL for production: postgresql+psycopg2://user:pass@host:5432/db
# SQLite for development: sqlite:///provisioning.db
ENV DATABASE_URL=""

# Redis queue configuration (set at runtime)
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

# FRP Server configuration (set at runtime)
ENV FRP_SERVER_ADDR=""
ENV FRP_DOMAIN=""
ENV FRP_DASHBOARD_PASSWORD=""

# SSH private key (base64-encoded or raw PEM). Written to ~/.ssh/id_ed25519 at startup.
ENV SSH_PRIVATE_KEY=""

# Ansible inventory management vars (base64-encoded or raw YAML). Written to /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml at startup.
ENV MANAGEMENT_VARS_YAML=""

# Authentication
ENV ENABLE_AUTH=false
ENV REGISTRY_URL=""
ENV REGISTRY_CACHE_TTL_SECONDS=300
ENV REGISTRY_CACHE_MAX_SIZE=256

# Admin
ENV ADMIN_SECRET=""

USER appuser
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]
CMD ["sh", "start.sh"]
