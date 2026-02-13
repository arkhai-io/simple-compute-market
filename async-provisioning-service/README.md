# Async Provisioning Service

Asynchronous VM provisioning service for a multi-agent compute marketplace. Agents submit provisioning requests via a REST API, and a background worker executes Ansible playbooks to manage virtual machines on bare-metal hosts.

**Tech stack:** FastAPI, SQLAlchemy, Redis, Ansible, Pydantic

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

Build and run both the API server and worker in a single container:

```bash
docker build -t async-provisioning-service .
docker run -p 8081:8081 --env-file .env.local async-provisioning-service
```

The container starts both processes via `start.sh` and exposes port 8081. A Docker `HEALTHCHECK` probes `/health` every 30 seconds.

Required environment variables:

```env
DATABASE_URL=sqlite:////app/data/provisioning.db   # or PostgreSQL connection string
REDIS_URL=redis://redis-host:6379/0
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/provision` | Submit a provisioning job (returns 202) |
| `GET` | `/provision` | List jobs (paginated, agent-scoped) |
| `GET` | `/provision/{job_id}` | Get job status and result |
| `GET` | `/provision/{job_id}/logs` | Get raw Ansible output |
| `POST` | `/provision/{job_id}/cancel` | Cancel a queued or running job |
| `GET` | `/health` | Health check |

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
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `MAX_CONCURRENT_JOBS` | `5` | Parallel jobs per worker |
| `DEFAULT_MAX_RETRIES` | `3` | Retry attempts for failed jobs |
| `RETRY_BACKOFF_INITIAL_SECONDS` | `60` | Initial retry delay |
| `ANSIBLE_TIMEOUT_SECONDS` | `1800` | Max playbook runtime |
| `ENABLE_AUTH` | `false` | ERC-8004 agent auth |
| `REGISTRY_URL` | *(none)* | Agent registry for verification |
| `ENABLE_RATE_LIMITING` | `false` | Per-agent rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | Max POST requests per agent/min |

---

## Makefile Targets

| Target | Description |
|---|---|
| `install` | Install dependencies with uv |
| `serve` | Start the API server |
| `worker` | Start the background worker |
| `clean` | Remove generated files and caches |
