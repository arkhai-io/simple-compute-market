FROM python:3.13-slim

# ── System deps (SSH for Ansible) ────────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client sshpass && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

RUN useradd --create-home appuser

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
    rm /tmp/requirements.yml

# ── Application code ────────────────────────────────────────────────
COPY --chown=appuser:appuser async-provisioning-service/src ./src
COPY --chown=appuser:appuser async-provisioning-service/start.sh ./

# ── IaC submodule (baked into image; can be overridden at runtime) ──
COPY --chown=appuser:appuser compute-provisioning-iac ./compute-provisioning-iac

# ── Environment ─────────────────────────────────────────────────────
ENV PYTHONPATH=/app/src
ENV ANSIBLE_CONFIG=/app/compute-provisioning-iac/ansible/ansible.cfg

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]

CMD ["sh", "start.sh"]
