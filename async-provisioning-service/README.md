# Async Provisioning Service

Asynchronous VM provisioning service for a multi-agent compute marketplace. Agents submit provisioning requests via a REST API, and a background worker executes Ansible playbooks to create, manage, and destroy virtual machines on bare-metal hosts.

**Tech stack:** FastAPI, SQLAlchemy, Redis, Ansible, asyncio, Pydantic

**Key capabilities:**
- Async job queue with Redis for decoupled API and worker processes
- Concurrent job execution with configurable parallelism (semaphore-based)
- Exponential backoff retries with circuit breaker for non-retryable errors
- Multi-agent isolation with ERC-8004 identity verification
- Real-time log streaming from Ansible playbook output
- Early PID capture enabling in-flight job cancellation

---

## Table of Contents

1. [Architecture](#architecture)
2. [Quick Start](#quick-start)
3. [API Reference](#api-reference)
4. [Authentication](#authentication)
5. [Multi-Agent Support](#multi-agent-support)
6. [Image Types](#image-types)
7. [Network Modes](#network-modes)
8. [Configuration Reference](#configuration-reference)
9. [VM Actions](#vm-actions)
10. [Retry and Error Handling](#retry-and-error-handling)
11. [Deployment](#deployment)
12. [Makefile Targets](#makefile-targets)

---

## Architecture

The service is split into two processes that communicate through a Redis queue:

```
                          +-----------------+
                          |   Redis Queue   |
                          | (provisioning   |
  Agent A ----+           |   _jobs)        |           +------------------+
              |           +--------+--------+           |  Ansible Playbook|
  Agent B --->+---> [ FastAPI :8081 ] --enqueue-->      |  (vm-operations) |
              |       |                         |       +------------------+
  Agent N ----+       |  PostgreSQL / SQLite    |              ^
                      |  (provisioning_jobs)    |<--- [ Worker (asyncio) ]
                      +-------------------------+       dequeue + execute
```

**Components:**

| Component | Description |
|---|---|
| **API Server** | FastAPI application on port 8081. Accepts provisioning requests, stores jobs in the database, and enqueues job IDs to Redis. |
| **Worker** | asyncio event loop that dequeues job IDs from Redis, executes Ansible playbooks concurrently (up to `MAX_CONCURRENT_JOBS`), and updates job status in the database. |
| **Redis Queue** | FIFO list (`provisioning_jobs`) used to pass job IDs from API to worker. Supports blocking pop with timeout. |
| **Database** | PostgreSQL (production) or SQLite (development). Stores job state, parameters, results, logs, retry metadata, and agent ownership. |
| **Ansible Playbooks** | Located in the `compute-provisioning-iac` submodule. The worker invokes `ansible-playbook` as a subprocess with per-job variable files. |

---

## Quick Start

### Prerequisites

- Python 3.10+
- Redis server
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
make install
```

### Running the Service

Start the API server and worker in separate terminals:

```bash
# Terminal 1 - API server
make serve

# Terminal 2 - Background worker
make worker
```

Or run both in the background:

```bash
make start-all
```

### Development Setup with SQLite

For local development without PostgreSQL, create a `.env.local` file:

```bash
make config-sample
```

Then edit `.env.local`:

```env
DATABASE_URL=sqlite:///provisioning.db
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=debug
MAX_CONCURRENT_JOBS=2
DEFAULT_MAX_RETRIES=3
RETRY_BACKOFF_INITIAL_SECONDS=30
ANSIBLE_TIMEOUT_SECONDS=600
```

Initialize the database and start:

```bash
make dev      # Checks Redis, initializes DB, shows next steps
make serve    # In terminal 1
make worker   # In terminal 2
```

The interactive API docs are available at `http://localhost:8081/docs`.

---

## API Reference

### `POST /provision` -- Submit a Provisioning Job

Submits a new VM provisioning job to the queue. Returns immediately with a job ID.

**Headers:**

| Header | Required | Description |
|---|---|---|
| `X-Agent-ID` | Yes (when auth enabled) | ERC-8004 agent identifier |
| `Content-Type` | Yes | `application/json` |

**Request body:**

| Field | Type | Default | Description |
|---|---|---|---|
| `vm_host` | string | `"ww1"` | KVM host from inventory |
| `vm_action` | string | `"create"` | VM operation (see [VM Actions](#vm-actions)) -- constrained to: `create`, `list`, `start`, `shutdown`, `destroy`, `reboot`, `undefine`, `monitor`, `reset_password`, `lease_end`, `lease_remove`, `check` |
| `vm_target` | string | `null` | VM name (libvirt domain). **Required for all actions except `list` and `check`** |
| `image_setup_type` | string | `"scratch"` | Image type: `"scratch"` or `"golden"` (see [Image Types](#image-types)) |
| `vm_ram` | integer | `null` | RAM in MB (512--32768). Ansible defaults from group_vars if unset |
| `vm_vcpus` | integer | `null` | Virtual CPUs (1--20). Ansible defaults from group_vars if unset |
| `vm_disk_size` | string | `null` | Disk size e.g. `"20G"`. Ansible defaults from group_vars if unset |
| `vm_os_variant` | string | `null` | OS variant for virt-install (e.g. `"ubuntu24.04"`) |
| `ssh_pubkey` | string | `null` | SSH public key for tenant user (optional -- keypair generated if unset) |
| `gpu_provisioned` | boolean | `null` | Enable GPU passthrough |
| `vm_gpu_count` | integer | `null` | Number of GPUs to auto-select (>=1) |
| `vm_gpu_device` | string | `null` | Single GPU PCI address (e.g. `"0000:01:00.0"`) |
| `vm_gpu_devices` | string[] | `null` | Multiple GPU PCI addresses |
| `vm_gpu_partition_size` | string | `null` | MIG/SR-IOV partition size (e.g. `"1g.5gb"`) |
| `frp_server_addr` | string | `null` | FRP server IP address |
| `frp_domain` | string | `null` | FRP base domain |
| `frp_dashboard_password` | string | `null` | FRP dashboard password (required when `frp_server_addr` is set) |
| `golden_image_name` | string | `null` | Golden image name override |
| `gcs_bucket_url` | string | `null` | GCS bucket URL for golden image |
| `gcs_image_path` | string | `null` | GCS image path for golden image |
| `vm_lease_end` | string | `null` | Lease end time in UTC (`"YYYY-MM-DD HH:MM"` format) |
| `max_retries` | integer | `null` | Override default max retry attempts (0--10) |

**Validation rules:**

- `vm_target` is required for all actions except `list` and `check`.
- `vm_lease_end` is required when `vm_action` is `lease_end`.
- `frp_dashboard_password` is required when `frp_server_addr` is set.
- `vm_action` is constrained to the 12 valid action literals listed above.
- `vm_lease_end` is interpreted as UTC.

**Example:**

```bash
curl -X POST http://localhost:8081/provision \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1" \
  -d '{
    "vm_host": "ww1",
    "vm_target": "agent-vm-01",
    "vm_action": "create",
    "vm_ram": 4096,
    "vm_vcpus": 2,
    "vm_disk_size": "20G",
    "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... agent@market",
    "gpu_provisioned": true,
    "frp_server_addr": "34.87.54.66",
    "frp_domain": "example.com",
    "frp_dashboard_password": "secret"
  }'
```

**Response (202 Accepted):**

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued"
}
```

---

### `GET /provision` -- List Jobs

Lists provisioning jobs with pagination. When authenticated, returns only the requesting agent's jobs.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `offset` | integer | `0` | Pagination offset (>= 0) |
| `limit` | integer | `20` | Page size (1-100) |
| `status` | string | `null` | Filter by status: `queued`, `running`, `succeeded`, `failed`, `cancelled` |

**Example:**

```bash
curl "http://localhost:8081/provision?status=running&limit=5" \
  -H "X-Agent-ID: eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
```

**Response (200 OK):**

```json
{
  "jobs": [
    {
      "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "status": "running",
      "params": {
        "ssh_pubkey": "ssh-ed25519 AAAAC3...",
        "vm_host": "vm1",
        "vm_target": "agent-vm-01",
        "vm_action": "create",
        "vm_ram": 4096,
        "vm_vcpus": 4,
        "vm_disk_size": "50G",
        "image_setup_type": "scratch"
      },
      "result": null,
      "error": null,
      "retry_count": 0,
      "max_retries": 3,
      "next_retry_at": null,
      "agent_id": "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 5
}
```

---

### `GET /provision/{job_id}` -- Job Status

Returns the full status of a single job, including retry information.

**Example:**

```bash
curl http://localhost:8081/provision/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response (200 OK):**

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "succeeded",
  "params": { "..." },
  "result": {
    "ssh_port": "7002",
    "tenant_user": "agentvm01",
    "vm_host_ip": "100.64.246.54",
    "ssh_command": "ssh -i <your_private_key> -p 7002 agentvm01@subdomain.example.com",
    "status": "success",
    "action": "create",
    "vm_name": "agent-vm-01",
    "host": "ww1",
    "authentication": {
      "tenant": { "password": "...", "key_type": "provided", "ssh_commands": { "external": "...", "internal": "..." } },
      "root": { "password": "...", "ssh_commands": { "external": "...", "internal": "..." } }
    },
    "frp": { "domain": "example.com", "enabled": true, "remote_port": "7002", "subdomain": "abc123" },
    "gpu": { "mode": "passthrough", "model": "NVIDIA ...", "pci_address": "0000:01:00.0", "provisioned": true },
    "vm_ip_internal": "192.168.122.x",
    "vm_state": "running",
    "ansible_result": { "...full structured output..." }
  },
  "error": null,
  "retry_count": 0,
  "max_retries": 3,
  "agent_id": "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
}
```

---

### `GET /provision/{job_id}/logs` -- Ansible Logs

Returns the raw Ansible playbook output for a job. Logs are updated in real-time while the job is running.

**Example:**

```bash
curl http://localhost:8081/provision/a1b2c3d4-e5f6-7890-abcd-ef1234567890/logs
```

**Response (200 OK):**

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "succeeded",
  "logs": "PLAY [VM Operations] ***\n\nTASK [Gathering Facts] ***\nok: [vm1]\n..."
}
```

---

### `POST /provision/{job_id}/cancel` -- Cancel a Job

Cancels a queued or running job. If the job is running, sends SIGTERM to the Ansible process. Agents can only cancel their own jobs.

**Example:**

```bash
curl -X POST http://localhost:8081/provision/a1b2c3d4-e5f6-7890-abcd-ef1234567890/cancel \
  -H "X-Agent-ID: eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
```

**Response (200 OK):**

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "cancelled",
  "message": "Job cancelled successfully"
}
```

**Error -- wrong agent (403 Forbidden):**

```json
{
  "detail": "Cannot cancel another agent's job"
}
```

---

### `GET /health` -- Health Check

```bash
curl http://localhost:8081/health
```

**Response (200 OK):**

```json
{
  "status": "ok"
}
```

---

## Authentication

Authentication uses the **ERC-8004 agent identity** standard. When enabled (`ENABLE_AUTH=true`), the service validates agent identity through the `X-Agent-ID` header.

### Agent ID Format

```
eip155:<chain_id>:0x<40_hex_address>:<token_id>
```

**Example:**

```
eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1
```

### Verification Flow

1. **Format validation** -- The `X-Agent-ID` header is checked against the ERC-8004 regex pattern.
2. **Registry verification** -- If `REGISTRY_URL` is configured, the agent is verified via `GET {registry_url}/agents/{url_encoded_id}`. The agent must have `status: "healthy"` or `exists: true`.
3. **TTL cache** -- Registry responses are cached for 5 minutes (configurable) with a max of 256 entries (configurable) to avoid excessive registry calls.
4. **Fail-open** -- If the registry is unreachable or returns an unexpected status code, the request is allowed through. Only an explicit 404 from the registry blocks access.

### Header Requirements

| Method | `X-Agent-ID` | Behavior |
|---|---|---|
| `POST` | **Required** (when auth enabled) | Returns 401 if missing or invalid format |
| `GET` | Optional | Used for agent-scoped filtering if provided |
| `GET /health` | Skipped | Health endpoint bypasses auth entirely |

---

## Multi-Agent Support

The service supports **N agents sharing a single provisioning service** with per-agent isolation.

### Job Isolation

- Each job records the `agent_id` of the submitting agent.
- When an authenticated agent calls `GET /provision`, they only see their own jobs.
- Unauthenticated requests (auth disabled) see all jobs.

### Cancellation Enforcement

- Agents can only cancel jobs they own.
- Attempting to cancel another agent's job returns `403 Forbidden`.
- Unauthenticated cancel requests are allowed for any job (when auth is disabled).

### Rate Limiting

Per-agent rate limiting uses a **sliding window counter** (in-memory). Disabled by default.

| Setting | Default | Description |
|---|---|---|
| `ENABLE_RATE_LIMITING` | `false` | Enable per-agent rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | Max POST requests per agent per minute |

When rate-limited, the API returns `429 Too Many Requests` with `Retry-After: 60` and `X-RateLimit-Remaining` headers.

---

## Image Types

The `image_setup_type` parameter controls how the VM disk image is built.

### Scratch (default)

Builds the VM from a base cloud image. The Ansible playbook downloads the base image, creates a new disk, and runs the full provisioning sequence including SSH key injection.

```json
{
  "image_setup_type": "scratch",
  "ssh_pubkey": "ssh-ed25519 AAAAC3..."
}
```

### Golden

Uses a pre-built golden image with the OS and software already installed. The service injects root credentials **server-side** from `management-vars.yaml` -- agents never see these credentials in their request or response.

```json
{
  "image_setup_type": "golden",
  "ssh_pubkey": "ssh-ed25519 AAAAC3..."
}
```

Server-side credentials loaded from `compute-provisioning-iac/ansible/inventory/management-vars.yaml`:
- `root_ssh_filename` -- SSH key filename for root access
- `root_ssh_password` -- Root password for the golden image
- `golden_image_name` -- Name of the pre-built image (optional)

---

## Network Modes

VM network connectivity is configured at the Ansible playbook level.

### Direct Port Forwarding (Legacy)

Uses iptables DNAT rules on the VM host to forward a random high port (10000-65000) to the VM's SSH port (22). The assigned port is returned in the job result as `ssh_port`.

```
Client --> vm_host_ip:random_port --> iptables DNAT --> vm_ip:22
```

Connection example:

```bash
ssh -i ~/.ssh/my_key -p 12345 tenant-user@10.0.0.5
```

### FRP Reverse Proxy

Uses [frp](https://github.com/fatedier/frp) to expose VM services through a reverse proxy with subdomain-based routing. FRP parameters are passed via the API request:

| Variable | Source | Description |
|---|---|---|
| `frp_server_addr` | API request | FRP server IP |
| `frp_domain` | API request | Base domain for subdomain routing |
| `frp_dashboard_password` | API request | Dashboard password for port allocation |

---

## Configuration Reference

All settings are configured via environment variables or `.env` / `.env.local` files.

### Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | API server bind address |
| `PORT` | `8081` | API server port |
| `LOG_LEVEL` | `info` | Logging level (`debug`, `info`, `warning`, `error`) |

### Data Stores

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/provisioning` | Database connection string (PostgreSQL or SQLite) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_QUEUE_NAME` | `provisioning_jobs` | Redis list key for the job queue |

### Ansible

| Variable | Default | Description |
|---|---|---|
| `ANSIBLE_TIMEOUT_SECONDS` | `1800` | Max time (seconds) for a single playbook run before it is killed |
| `DEFAULT_VM_HOST` | `ww1` | Default inventory host if not specified in request |
| `PLAYBOOK_PATH` | *(auto-detected)* | Override path to `vm-operations.yaml` playbook |
| `INVENTORY_PATH` | *(auto-detected)* | Override path to Ansible inventory file |
| `PROVISIONING_REPO_ROOT` | *(auto-detected)* | Override root directory for locating the `compute-provisioning-iac` submodule |

### Worker Concurrency

| Variable | Default | Description |
|---|---|---|
| `MAX_CONCURRENT_JOBS` | `5` | Maximum number of jobs processed simultaneously per worker |

### Retry

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_MAX_RETRIES` | `3` | Default retry attempts for failed jobs |
| `RETRY_BACKOFF_INITIAL_SECONDS` | `60` | Initial delay before first retry |
| `RETRY_BACKOFF_MULTIPLIER` | `2.0` | Exponential backoff multiplier |
| `RETRY_BACKOFF_MAX_SECONDS` | `3600` | Maximum delay between retries (1 hour cap) |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `ENABLE_AUTH` | `false` | Enable ERC-8004 agent authentication |
| `REGISTRY_URL` | *(none)* | Agent registry API URL for verification |
| `REGISTRY_CACHE_TTL_SECONDS` | `300` | TTL for registry lookup cache (5 minutes) |
| `REGISTRY_CACHE_MAX_SIZE` | `256` | Maximum entries in the registry cache |

### Rate Limiting

| Variable | Default | Description |
|---|---|---|
| `ENABLE_RATE_LIMITING` | `false` | Enable per-agent sliding window rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `30` | Maximum POST requests per agent per minute |

### Networking

| Variable | Default | Description |
|---|---|---|
| `ZEROTIER_NETWORK` | *(none)* | ZeroTier network ID for overlay networking between services |

---

## VM Actions

The `vm_action` parameter determines which operation the Ansible playbook performs.

| Action | Description |
|---|---|
| `create` | Create a new VM with the specified resources and SSH key |
| `list` | List VMs and their status on the target host |
| `start` | Start a stopped VM |
| `shutdown` | Gracefully shut down a running VM |
| `destroy` | Force-stop a running VM |
| `reboot` | Reboot a running VM |
| `undefine` | Remove a VM definition and clean up all associated resources (disk, network rules) |
| `monitor` | Check VM status and resource usage |
| `reset_password` | Reset the VM user password |
| `lease_end` | Set or update the lease expiration time (requires `vm_lease_end` parameter) |
| `lease_remove` | Remove the lease expiration from a VM |
| `check` | Query available capacity on the host -- returns free CPU, RAM, and GPU resources |

---

## Retry and Error Handling

Failed jobs are automatically retried with exponential backoff, unless the error matches a non-retryable pattern.

### Exponential Backoff

The delay before each retry is calculated as:

```
delay = min(initial_seconds * (multiplier ^ retry_count), max_seconds)
```

With default settings (`initial=60s`, `multiplier=2.0`, `max=3600s`):

| Retry | Delay |
|---|---|
| 1st | 60 seconds |
| 2nd | 120 seconds |
| 3rd | 240 seconds |

Total worst-case retry overhead: approximately 7 minutes for 3 retries.

### Circuit Breaker (Non-Retryable Errors)

The following error patterns cause immediate failure without retrying, since these errors will not resolve on their own:

| Error Pattern | Reason |
|---|---|
| `Invalid SSH key` | Bad input from the agent |
| `VM target not found` | Nonexistent VM name |
| `Permission denied` | Insufficient privileges |
| `Authentication failed` | Credential issue |
| `Host unreachable` | Network configuration problem |
| `Operation timed out` | SSH connection timeout |
| `Connection refused` | SSH port not open |
| `UNREACHABLE` | Ansible unreachable host status |
| `Failed to get "resize" lock` | Disk image already in use by another process |
| `Is another process using the image` | Disk image lock conflict |
| `Cannot determine IP address for VM` | VM already cleaned up/undefined |
| `failed to get domain` | libvirt domain not found |
| `Domain not found` | VM no longer exists |

### Job Lifecycle

```
queued --> running --> succeeded
                  \--> failed (non-retryable or max retries exceeded)
                  \--> queued (retryable, re-enqueued with backoff)
queued --> cancelled (user-initiated)
running --> cancelled (user-initiated, SIGTERM sent to process)
```

### Per-Job Retry Override

Agents can override the default max retries per job:

```bash
curl -X POST http://localhost:8081/provision \
  -H "Content-Type: application/json" \
  -d '{
    "ssh_pubkey": "ssh-ed25519 AAAAC3...",
    "vm_action": "create",
    "max_retries": 0
  }'
```

Setting `max_retries: 0` disables retries for that job.

---

## Deployment

### Development

Uses SQLite for zero-dependency local development:

```bash
DATABASE_URL=sqlite:///provisioning.db make dev
```

### Production

Requires PostgreSQL and Redis:

```bash
export DATABASE_URL="postgresql+psycopg2://user:password@db-host:5432/provisioning"
export REDIS_URL="redis://redis-host:6379/0"
export MAX_CONCURRENT_JOBS=5
export DEFAULT_MAX_RETRIES=3
export RETRY_BACKOFF_INITIAL_SECONDS=60
export ANSIBLE_TIMEOUT_SECONDS=1800
export ENABLE_AUTH=true
export REGISTRY_URL="https://registry.example.com"

make serve   # API server
make worker  # Background worker
```

### Database Setup

The database schema is created automatically on first run via SQLAlchemy's `create_all()`. No manual migration step is needed.

---

## Makefile Targets

| Target | Description |
|---|---|
| `install` | Install dependencies using uv |
| `serve` | Start the provisioning service API server |
| `worker` | Start the background worker |
| `start-all` | Start both API and worker in the background |
| `stop-all` | Stop all background services |
| `dev` | Set up development environment (checks Redis, initializes DB) |
| `test` | Run tests |
| `test-cov` | Run tests with coverage report |
| `test-integration` | Run integration tests (requires Redis) |
| `db-init` | Initialize database (create tables via SQLAlchemy) |
| `db-reset` | Reset database (deletes all data) |
| `db-show-jobs` | Show recent provisioning jobs (SQLite only) |
| `health` | Check the API health endpoint |
| `queue-status` | Show Redis queue length and recent job IDs |
| `queue-clear` | Clear the Redis queue (deletes all queued jobs) |
| `status` | Check if API, worker, and Redis are running |
| `logs` | Show the logs directory |
| `clean` | Remove generated files and caches |
| `config-sample` | Create `.env.local` from `.env.sample` |
