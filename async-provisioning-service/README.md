# Async Provisioning Service

Asynchronous VM provisioning service for a multi-agent compute marketplace. Agents submit provisioning requests via a REST API, and a background worker executes Ansible playbooks to manage virtual machines on bare-metal hosts.

**Tech stack:** FastAPI, SQLAlchemy, Redis, Ansible, Pydantic

## Architecture

```
Client ──▶ FastAPI (port 8081) ──▶ Redis queue ──▶ Worker ──▶ Ansible playbooks
                                                              (compute-provisioning-iac)
```

| Component | Description |
|---|---|
| **API Server** | FastAPI on port 8081. Accepts requests, stores jobs, enqueues to Redis. |
| **Worker** | asyncio loop that dequeues jobs, runs Ansible playbooks concurrently, updates status. |
| **Redis** | FIFO queue (`provisioning_jobs`) passing job IDs from API to worker. |
| **Database** | PostgreSQL (production) or SQLite (development). Stores job state, results, logs. |

---

## Quick Start

**Prerequisites:** Python 3.10+, Redis, [uv](https://docs.astral.sh/uv/)

```bash
make install                # Install dependencies
cp .env.sample .env.local   # Configure environment
make serve                  # Terminal 1 - API server
make worker                 # Terminal 2 - Background worker
```

API docs available at `http://localhost:8081/docs`.

---

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

# Dev — mounts host IaC + SSH keys for live edits
make docker-run-dev
```

The container starts both processes via `start.sh` and exposes port 8081. A Docker `HEALTHCHECK` probes `/health` every 30 seconds.

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

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/jobs` | Submit a provisioning job (returns 202) |
| `GET` | `/api/v1/jobs` | List jobs (paginated, sortable, agent-scoped) |
| `GET` | `/api/v1/jobs/{job_id}` | Get job status and result |
| `GET` | `/api/v1/jobs/{job_id}/logs` | Get raw Ansible output |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Cancel a queued or running job |
| `GET` | `/health` | Deep health check (API + DB + Redis) |

**Query parameters for `GET /api/v1/jobs`:**

| Parameter | Default | Description |
|---|---|---|
| `offset` | `0` | Pagination offset |
| `limit` | `20` | Max results per page (1-100) |
| `status` | *(all)* | Filter: `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `sort` | `created_at_desc` | Sort order: `created_at_asc` or `created_at_desc` |

---

## Authentication

Uses **ERC-8004 agent identity** via the `X-Agent-ID` header. Enable with `ENABLE_AUTH=true`.

Agent ID format: `eip155:<chain_id>:0x<40_hex_address>:<token_id>`

| Method | `X-Agent-ID` | Behavior |
|---|---|---|
| `POST` | Required (when auth enabled) | 401 if missing or invalid |
| `GET` | Optional | Scopes results to agent if provided |
| `GET /health` | Skipped | Bypasses auth |

Agents can only see and cancel their own jobs. Registry verification is optional via `REGISTRY_URL` with TTL caching and fail-open semantics.

---

## VM Actions

| Action | Description |
|---|---|
| `create` | Create a new VM |
| `list` | List VMs on the host |
| `start` / `shutdown` / `reboot` / `destroy` | VM power management |
| `undefine` | Remove VM and clean up resources |
| `monitor` | Check VM status and resource usage |
| `reset_password` | Reset VM user password |
| `lease_end` / `lease_remove` | Manage lease expiration |
| `check` | Query available host capacity |

---

## Configuration

All settings via environment variables or `.env` / `.env.local` files.

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | API bind address |
| `PORT` | `8081` | API port |
| `LOG_LEVEL` | `info` | Logging level |
| `DATABASE_URL` | `postgresql+psycopg2://...` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for job queue |
| `MAX_CONCURRENT_JOBS` | `5` | Parallel jobs per worker |
| `DEFAULT_MAX_RETRIES` | `3` | Retry attempts for failed jobs |
| `RETRY_BACKOFF_INITIAL_SECONDS` | `60` | Initial retry delay |
| `ANSIBLE_TIMEOUT_SECONDS` | `1800` | Max seconds per Ansible run |
| `DEFAULT_VM_HOST` | `ww1` | Default KVM host target |
| `PROVISIONING_REPO_ROOT` | *(auto-detected)* | Override project root path |
| `PLAYBOOK_PATH` | *(auto-resolved)* | Override playbook path |
| `INVENTORY_PATH` | *(auto-resolved)* | Override inventory path |
| `ENABLE_AUTH` | `false` | Enable agent authentication |
| `REGISTRY_URL` | *(none)* | Agent registry for verification |
| `ENABLE_RATE_LIMITING` | `false` | Enable per-agent rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | Max POST requests per agent/min |

---

## Makefile Targets

| Target | Description |
|---|---|
| `install` | Install dependencies with uv |
| `serve` | Start the API server |
| `worker` | Start the background worker |
| `docker-build` | Build Docker image (from repo root) |
| `docker-run` | Run with baked-in IaC |
| `docker-run-dev` | Run with host IaC + SSH keys mounted |
| `clean` | Remove generated files and caches |
