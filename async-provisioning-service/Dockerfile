FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

# Install ansible (needed at runtime to run playbooks)
RUN pip install --no-cache-dir ansible-core && \
    ansible-galaxy collection install community.general community.docker

RUN useradd --create-home appuser

WORKDIR /app
RUN chown appuser:appuser /app

USER appuser

# --- Python dependencies (from async-provisioning-service context) ---
COPY --chown=appuser:appuser async-provisioning-service/pyproject.toml async-provisioning-service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser async-provisioning-service/src ./src
COPY --chown=appuser:appuser async-provisioning-service/start.sh ./

# --- Ansible IaC (from compute-provisioning-iac) ---
COPY --chown=appuser:appuser compute-provisioning-iac/ansible /app/compute-provisioning-iac/ansible

ENV PYTHONPATH=/app/src
ENV PROVISIONING_REPO_ROOT=/app
ENV PLAYBOOK_PATH=/app/compute-provisioning-iac/ansible/playbooks/single-tenant/vm-operations.yaml
ENV INVENTORY_PATH=/app/compute-provisioning-iac/ansible/inventory/hosts

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]

CMD ["sh", "start.sh"]
