# async-provisioning-service

Async VM provisioning service. Exposes a REST API that queues provisioning jobs (create, destroy, start, stop, etc.) onto a Redis-backed worker that executes Ansible playbooks from the `compute-provisioning-iac` submodule.

For the deployed full-stack path, start with `docs/standup/overview.md` and use
`docs/standup/provisioning.md` as the operator runbook. This README still covers
local development and service internals.

## Architecture

```
Client ──▶ FastAPI (port 8081) ──▶ Redis queue ──▶ Worker ──▶ Ansible playbooks
                                                              (compute-provisioning-iac)
```

## Local Development

```bash
# Install dependencies
make install

# Copy and configure environment
cp .env.sample .env.local

# Start API server
make serve

# Start background worker (separate terminal)
make worker
```

## Docker

### Prerequisites

Initialize the `compute-provisioning-iac` submodule (the Dockerfile copies it into the image):

```bash
git submodule update --init compute-provisioning-iac
```

### Build

```bash
make docker-build
```

This runs from the repo root so both `async-provisioning-service/` and `compute-provisioning-iac/` are in the build context.

### Run

```bash
# Basic — uses baked-in IaC
make docker-run

# Dev — mounts host IaC for live edits
make docker-run-dev
```

### Mounting specific files at runtime

Override only what you need:

```bash
# Mount inventory + SSH keys
docker run --rm --env-file .env.local -p 8081:8081 \
  -v /path/to/hosts:/app/compute-provisioning-iac/ansible/inventory/hosts:ro \
  -v /path/to/keys:/app/compute-provisioning-iac/ansible/keys:ro \
  async-provisioning-service

# Full IaC override (entire submodule)
docker run --rm --env-file .env.local -p 8081:8081 \
  -v $(pwd)/../compute-provisioning-iac:/app/compute-provisioning-iac \
  async-provisioning-service
```

### Mount points reference

| Container path | Purpose |
|---|---|
| `/app/compute-provisioning-iac/` | Entire IaC submodule (full override) |
| `/app/compute-provisioning-iac/ansible/inventory/hosts` | Ansible inventory |
| `/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml` | Management variables |
| `/app/compute-provisioning-iac/ansible/keys/` | SSH private keys |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | API bind address |
| `PORT` | `8081` | API port |
| `LOG_LEVEL` | `info` | Logging level |
| `DATABASE_URL` | `postgresql+psycopg2://...` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for job queue |
| `ANSIBLE_TIMEOUT_SECONDS` | `1800` | Max seconds per Ansible run |
| `ANSIBLE_BECOME_PASS` | *(required in deployed envs)* | `become` password for the target KVM host |
| `DEFAULT_VM_HOST` | `ww1` | Default KVM host target |
| `PROVISIONING_REPO_ROOT` | *(auto-detected)* | Override project root path |
| `PLAYBOOK_PATH` | *(auto-resolved)* | Override playbook path |
| `INVENTORY_PATH` | *(auto-resolved)* | Override inventory path |
| `ENABLE_AUTH` | `false` | Enable agent authentication |
| `AUTH_FAIL_OPEN` | `false` | When auth is enabled, allow registry outages to bypass agent verification |
| `ENABLE_RATE_LIMITING` | `false` | Enable per-agent rate limiting |
| `FRP_SERVER_ADDR` | *(required in deployed envs)* | FRP server hostname or IP |
| `FRP_DOMAIN` | *(required in deployed envs)* | FRP routing domain |
| `FRP_DASHBOARD_PASSWORD` | *(required in deployed envs)* | FRP dashboard API password |
| `SSH_PRIVATE_KEY` | *(required in deployed envs)* | Base64 or raw provisioner SSH private key |
| `MANAGEMENT_VARS_YAML` | *(required in deployed envs)* | Base64 or raw `management-vars.yaml` contents |

For deployed environments, do not start from `.env.sample` directly. Use
`.env.production.sample` and keep `ENABLE_AUTH=true`, `AUTH_FAIL_OPEN=false`,
and a real `REGISTRY_URL`.
