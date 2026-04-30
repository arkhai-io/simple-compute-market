# Arkhai Market Stack — Architecture Reference

> **Purpose:** This document is intended to initialize AI-assisted development sessions with accurate, up-to-date context about the repository structure, service responsibilities, data flows, and known problem areas. Treat it as a living document — update it as understanding deepens.

---

## Repository Overview

**Simple Market Service (SMS)** is a reference implementation of an agent-driven compute marketplace. Autonomous buyer and seller agents discover each other, negotiate prices, and settle agreements on-chain using Alkahest smart contracts. Physical compute (VMs) is provisioned post-settlement via Ansible.

The stack is designed so that in production, multiple independent seller nodes each run their own agent + provisioning stack, while buyers can be ephemeral (a CLI invocation or a long-running agent). The `test-env` component exists only for local development.

### Technology Anchors

| Concern | Technology |
|---|---|
| On-chain settlement / escrow | [Alkahest](https://github.com/arkhai-io/alkahest) contracts |
| Agent identity & discovery | [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) (ERC-721-based agent registry) |
| Buyer ↔ seller protocol | Plain HTTP request/response, EIP-191-signed bodies |
| Seller server framework | FastAPI / Starlette + uvicorn |
| Buyer | Pure HTTP client — `market` CLI, no server |
| VM automation | Ansible (via `compute-provisioning-iac` submodule) |
| Job queue | In-process `asyncio.Queue` (no external queue dependency) |
| Overlay networking (optional) | ZeroTier |
| Local dev chain | Anvil (Foundry) |

> **Asymmetric topology.** Earlier iterations of this stack had buyer
> *and* seller running symmetric agents based on Google ADK and the
> A2A agent-to-agent protocol — both sides hosted HTTP servers and
> exchanged push messages. That has been retired. Today only the
> seller runs a server (the **storefront**, exposed by
> `market-storefront serve`); the buyer is a pure HTTP client driven
> by the `market` CLI. Negotiation is a sequence of synchronous
> request/response calls from the buyer to the seller's storefront
> over plain HTTP, with bodies authenticated via EIP-191 wallet
> signatures. There is no agent runtime framework — `agent.py` on the
> seller side is plain Python that wires Starlette routes to policy
> evaluation.

---

## Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EVM Chain (Alkahest)                         │
│   IdentityRegistry · ReputationRegistry · ValidationRegistry       │
│   Alkahest escrow contracts                                         │
└──────────────────┬──────────────────────┬───────────────────────────┘
                   │ events / txns         │ events / txns
         ┌─────────▼──────────┐   ┌───────▼────────────────┐
         │  registry-service  │   │  storefront            │
         │  :8080             │   │  :8001 (seller only)   │
         │  FastAPI indexer   │◄──┤  FastAPI/Starlette     │
         │  SQLite/Postgres   │   │  market-storefront serve│
         └─────────▲──────────┘   └───────┬────────────────┘
                   │  GET /listings            │ HTTP (provisioning API)
                   │  signed reqs    ┌────────▼────────────────┐
                   │                 │ provisioning-service    │
         ┌─────────┴──────────┐      │   API  :8081  (FastAPI) │
         │  buyer (`market`)  ├─────▶│   Job loop (in-process) │
         │  pure HTTP client  │ HTTP └────────┬────────────────┘
         │  no server         │ buyer→seller  │ asyncio.Queue
         │  signed bodies     │      ┌────────▼────────────────┐
         └────────────────────┘      │  Ansible playbooks      │
                                     │  (compute-provisioning- │
                                     │   iac submodule)        │
                                     └─────────────────────────┘

 ┌──────────────┐   ┌────────────────────────────────────────┐
 │  test-env    │   │  Operator CLIs                         │
 │  Anvil node  │   │   market           — buyer runtime     │
 │  (dev only)  │   │   market-storefront — seller runtime   │
 └──────────────┘   │   market-policy    — train/eval/export │
                    │   market-infra     — chain/registry/zt │
                    └────────────────────────────────────────┘
```

Negotiation flow: the buyer's `market buy`/`market negotiate`
discovers seller orders from `registry-service`, then issues
synchronous signed POSTs against the seller's storefront
(`/negotiate`, `/listings/...`, `/settle/{escrow_uid}`). The seller's
storefront evaluates each request through the policy engine, decides
counter/accept/exit, and returns the next round inline. There are no
push messages and no symmetric agent-to-agent protocol — the buyer
drives every round.

---

## Component Summaries

### `test-env`

**Role:** Local development chain fixture.

An Anvil (Foundry) instance with Alkahest contracts pre-deployed and chain state saved to `test-env/state/state.json`. The Dockerfile loads this snapshot at startup, giving a deterministic chain for every dev session. Restarting the container resets chain state.

In production this component is absent — the agent and registry configs point to a live RPC endpoint (e.g., Base Sepolia or mainnet).

**Key facts:**
- Default port: `8545`
- State is generated by the root `build-anvil-state` Makefile target, which runs the `market-contract-deployer` image against a fresh Anvil and dumps the resulting state
- Contract addresses from the baked state are written to `shared-env/.env`, which buyer/seller agent containers source at runtime

> **TODO:** Document the exact set of Alkahest contracts deployed and their addresses in the baked state.

---

### `registry-service`

**Role:** Off-chain indexer and discovery service for on-chain agent/order state.

FastAPI service that watches the EVM chain for ERC-8004 events (`AgentRegistered`, `MetadataSet`, `UriUpdated`) and maintains a queryable local database. Also serves the **Orders API** — agents publish open orders here so counterparties can discover them.

**Ports:** `8080` (default)

**Databases:**
- Dev: SQLite (`registry.db`)
- Prod: PostgreSQL

**Key APIs:**
- `GET /agents` — discover registered agents
- `GET /agents/{agentId}` — agent detail + health status
- `POST /agents/{agentId}/heartbeat` — agents POST signed heartbeats to stay "healthy"
- `POST /agents/{agentId}/listings` — publish/update an order
- `GET /listings` — global order book query (filter by resource type, region, GPU model, SLA, status)
- `PUT /listings/{listing_id}` — update order status (e.g., mark accepted/closed)

**Agent identity format (ERC-8004 canonical):**
```
eip155:{chainId}:{identityRegistryAddress}:{numericAgentId}
```
Example: `eip155:1337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:22`

**Source layout:**
```
registry-service/src/
├── api/             # FastAPI routes (agent_routes, order_routes)
├── contracts/       # ABI + web3.py interaction layer
├── db/              # SQLAlchemy models + Alembic migrations (7 versions so far)
├── services/        # event_sync.py (chain watcher), health_check.py
├── types/
└── main.py
```

> **TODO:** Document the event sync polling interval and any known lag or missed-event issues.
> **TODO:** Document the symmetric order concept visible in the test suite (`test_symmetric_orders.py`).

---

### `storefront` (Seller-side server)

**Role:** The seller's HTTP server. Hosts the `/listings/...`,
`/negotiate`, `/settle/{escrow_uid}`, `/alerts/resource`, and
`.well-known/erc-8004-registration.json` endpoints that buyers and the
provisioning service call. Runs as `market-storefront serve` (uvicorn,
FastAPI/Starlette). Internally it uses Alkahest (`alkahest_py` — a
pre-built `.whl` in `storefront/packages/`) for on-chain escrow
operations.

There is no agent runtime framework — `agent.py` is plain Python that
wires Starlette routes to the policy evaluation engine in
`market_policy`. There is no `google.adk`, no A2A push protocol, and
no symmetric agent-to-agent server on the buyer side. The earlier
"core agent" served both roles via ADK + A2A; both have been retired.

**Ports:** `8001` (default seller port; `seller.port` in config.toml).

**Startup sequence:** `entrypoint.sh` starts the ZeroTier daemon,
then `exec market-storefront serve`. On `@app.on_event("startup")` the
server joins the configured ZeroTier network if any, then runs
`_ensure_agent_identity()`:

- If `seller.onchain_agent_id` is set in config (fast path) — use that
  ID directly, no chain interaction.
- If `seller.auto_register = true` (default) and no ID is set — call
  `perform_registration()`, hold the resolved numeric ID in the
  module-level `_AGENT_ID` for the process lifetime, and log a hint to
  pin it in config.
- If `seller.auto_register = false` and no ID is set — raise
  `RuntimeError` immediately. The pod crashes with a clear message
  rather than silently minting a new on-chain identity.

After identity is resolved, the heartbeat sender, resource poller, and
negotiation watchdog are started as background tasks.

The `market-storefront register` console verb still exists and works
identically to before — operators can run it manually to inspect or
update registration. It now delegates to the shared `perform_registration()`
helper extracted from the same module.

**Key source layout:**
```
storefront/src/market_storefront/
├── cli.py                  # `market-storefront` console-script entry
├── commands/
│   ├── register.py         # in-process port of the legacy register_onchain.py
│   └── serve.py            # uvicorn launch
├── groups/                 # CLI groups: config, escrow, network
├── cli_provide.py          # `provide` (publish sell orders from DB)
├── cli_portfolio.py        # `portfolio import-csv`
├── cli_logs.py             # `logs show / status` (SQLite-backed seller stage events)
├── cli_common.py
├── server.py               # uvicorn entrypoint
├── agent.py                # Starlette routes, policy wiring, startup hooks
├── resource_poller.py      # Background resource state polling
├── negotiation_watchdog.py # Background task; monitors stuck negotiations
├── agent_heartbeat.py      # Heartbeat sender to registry
├── policy/seeding.py       # Default policy seeding for the seller role
├── utils/
│   ├── config.py           # Typed Config dataclass (CONFIG singleton, TOML-only)
│   ├── sqlite_client.py    # SQLite DB wrapper
│   ├── action_executor.py  # Executes policy actions (send offers, call provisioning, …)
│   ├── sync_negotiation.py # Synchronous /negotiate handler that drives one round
│   └── …
├── schema/pydantic_models.py
└── data/                   # Bundled token/alkahest address registries
```

The legacy `core/agent/app/` tree is gone. Files that lived there
either moved into `storefront/src/market_storefront/` (server,
resource poller, watchdog, action executor) or into the standalone
`market-policy` package (policy store, manager, registry, evaluator,
composite, negotiation thread, action builders).

**Policy system:** lives in `market-policy` (package: `policy/`,
import: `market_policy`). Policies are named callables registered
with `@policy_callable("name")` and stored in a `PolicyStore`. When a
negotiation request hits the storefront, the evaluator runs the
registered chain until one returns an action
(`accept` / `reject` / `counter` / `exit`). The seller seeds its
default policies at server startup via
`market_storefront.policy.seeding.ComputePolicySeeder`. The buyer
side imports the same engine at CLI invocation time but does not run a
server.

**Critical policy wiring detail:** `PolicyStore.__init__` creates an **empty** `self._registry = {}`. The `@policy_callable` decorators populate the module-level `CALLABLE_REGISTRY` dict in `market_policy.registry`. These two are only connected by an explicit call to `policy_store.register_callables(CALLABLE_REGISTRY)`. `PolicyManager.initialize()` does this wiring at startup. Any code that creates a fresh `PolicyStore` instance (controllers, tests, seed endpoints) **must** call `register_callables` before evaluating policies, or `evaluate_policy` will always return `None` despite callables being registered in `CALLABLE_REGISTRY`.

**`domain/` package — not installed, on sys.path:** `domain/compute/agent/app/policy/store.py` contains the actual `@policy_callable` decorated functions the storefront uses. The `domain/` tree is not a pip-installable package — it is copied into the Docker image at `/app/domain/` and requires `/app` to be on `sys.path`. The Dockerfile sets `ENV PYTHONPATH="/app"` to ensure this. The `POST /admin/policy/seed` endpoint also does a defensive `sys.path` check as a fallback. `domain.compute.agent.app.policy.arkhai_common` always fails to import (requires `gymnasium`) — this is expected and non-fatal; the module we actually need is `store.py`, which has no ML dependencies.

**Local state — SQLite:** the storefront maintains a SQLite database
(`seller.db_path`) containing policy configuration, order history,
negotiation threads, and the resource portfolio. This is a known area
of complexity — see Known Issues below.

**Docker build pattern — two-phase uv install:**

The storefront Dockerfile uses a two-stage build to cache the heavy
dependency install separately from the volatile project source:

1. **Builder stage** — runs `uv sync --no-install-project` to populate
   `.venv` with all third-party and internal-wheel dependencies. The
   project package itself is deliberately excluded so this layer is
   only invalidated when `pyproject.toml` or `uv.lock` change.

2. **Runtime stage** — copies the pre-built `.venv` from the builder,
   then copies the project source, then runs a completing
   `uv sync --no-dev --find-links /dist` (without `--no-install-project`)
   to install the project package and write the `market-storefront`
   console script to `.venv/bin/`.

Omitting the completing `uv sync` in the runtime stage means
`market-storefront` is absent from `.venv/bin/` and `entrypoint.sh`
exits 127. Both stages must be present for the console script to work.

**Critical: `/dist/` must be sourced from the build context in both stages.**

The runtime stage's completing `uv sync` must `COPY .dist/ /dist/`
directly from the build context — **not** `COPY --from=builder /dist /dist`.
The builder's `/dist/` layer is cached independently of `.dist/` on disk:
if `pyproject.toml` and `uv.lock` are unchanged, Docker reuses the builder
cache and the runtime stage receives whatever wheels were baked at the last
full rebuild, silently ignoring any `make dist` runs since. Sourcing from
the build context ensures the runtime layer invalidates whenever `.dist/`
changes, keeping installed internal packages in sync with the host.

**BuildKit context cache and when to use `make build-no-cache`:**

BuildKit caches the build context transfer keyed on file contents. If
`.dist/` was excluded from the context during earlier builds (e.g., by a
stale `.dockerignore`), BuildKit's cached context snapshot will not contain
the wheels even after the ignore file is corrected — subsequent `make build`
runs serve the poisoned snapshot. `make build-no-cache` passes `--no-cache`
to `docker build`, which forces BuildKit to re-evaluate the context from disk
and invalidates all layer cache. Use it when:

- A `.dockerignore` change is not being reflected in the context transfer size
- A `make dist` run is not being picked up despite the correct Dockerfile setup
- Any situation where the build completes without error but the wrong package
  version ends up in the container

Under normal operation (`.dist/` correctly in context, no ignore file issues),
`make build` is sufficient — BuildKit will invalidate the `COPY .dist/ /dist/`
layer whenever wheel file contents change.

> **TODO:** Document Alkahest escrow mechanics — what on-chain calls
> are made at which points in the negotiation.
> **TODO:** Document the SQLite schema and known
> statefulness/concurrency issues.
> **TODO:** Document the `negotiation_watchdog` — what conditions
> trigger it and what it does to orphaned negotiations.

#### Storefront API Surface (`controllers/`)

The storefront exposes a structured REST API via a `controllers/` package,
mirroring the provisioning service's controller pattern. All controllers are
mounted in `server.py` alongside the legacy `a2a_app` routes.

**System controller** (`controllers/system_controller.py`) — HTTP layer only; all logic in `services/system_service.py`:
```
GET  /health                            Kubernetes liveness/readiness probe
GET  /api/v1/system/health              Versioned alias
GET  /api/v1/system/status              Diagnostic snapshot: DB health + global pause state
POST /admin/policy/seed                 Discover @policy_callable decorators + seed default DB rows (admin key)
GET  /api/v1/system/policy              Callable registry + seeded policies with components_resolvable flag
POST /api/v1/system/policy/evaluate     Dry-run a synthetic order_create event through the policy engine (no writes)
```

**Listings controller** (`controllers/listings_controller.py`):
```
GET  /api/v1/listings                      List local listings (filter: status, paused, limit, offset)
GET  /api/v1/listings/{listing_id}         Single listing detail (includes paused flag)
POST /api/v1/listings/{listing_id}/pause   Take listing off market — admin key required
POST /api/v1/listings/{listing_id}/resume  Unpause + publish to registry — admin key required
```

`resume_listing` calls `publish_order_to_registry(row)` after clearing the paused flag. This is idempotent if the listing was already published, and is the **required step** to push a listing that was created with `paused=True`.

**Negotiations controller** (`controllers/negotiations_controller.py`):
```
GET  /api/v1/listings/{listing_id}/negotiations                        List threads (filter: terminal_state, buyer_address)
GET  /api/v1/listings/{listing_id}/negotiations/{neg_id}               Full detail: thread + messages + stage_events
POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance       Admin: drive one round — admin key required
POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept  Admin: commit terminal-success — admin key required
```

**Admin controller** (`controllers/admin_controller.py`):
```
POST /admin/pause    Set globally paused = True — admin key required
POST /admin/resume   Set globally paused = False — admin key required
GET  /admin/status   Live counts: active_negotiations, open_orders, paused_orders — admin key required
```

#### Admin API Key

A global admin API key gates all admin-only endpoints. Read from
`CONFIG.admin_api_key` (`[seller].admin_api_key` in config.toml, or injected
via the Helm secrets profile as a `config-storefront-secrets.yml` entry).
Enforced by `AdminAuthMiddleware` via the `X-Admin-Key` header. When
`admin_api_key` is `None` (local dev default), the middleware is a no-op.

Protected paths: any route under `/admin/`, and any route ending in `/pause`,
`/resume`, `/advance`, or `/force-accept`.

**Helm TODO:** Add `global.adminApiKey` to `values.yaml`; render into both
`config-storefront-secrets.yml` and `config-provisioning-secrets.yml` (for
the provisioning test controller). See Deployment Topology → Helm section.

#### Global Pause and Per-Order Pause

**Global pause** (`_GLOBALLY_PAUSED` flag in `server.py`): when `True`, all
`POST /negotiate/new` requests return 503 with machine-readable body
`{"error": "paused", "reason": "global", "hint": "..."}`. In-flight
negotiations are not interrupted. Toggled via `POST /admin/pause|resume`.

**Per-listing pause** (`paused` INTEGER column on the `listings` table, default 0):
when set for a specific listing, `POST /negotiate/new` against that listing returns
503 with `{"reason": "order:<listing_id>"}`. Toggled via
`POST /api/v1/listings/{id}/pause|resume`.

Listings can be **created already-paused** by passing `"paused": true` in the
`POST /orders/create` body. This threads through the policy pipeline:
`agent.py` reads the flag from the request body → adds it to `OrderCreateEvent.data["paused"]`
→ `oc_action_make_offer_from_order_create` in `domain/compute/agent/app/policy/store.py`
propagates it into `action.parameters["paused"]`
→ `action_executor.py` MAKE_OFFER handler writes the listing to SQLite with `paused=1`
and **skips** `publish_order_to_registry`.
The listing is invisible to buyers until `POST /api/v1/listings/{id}/resume` is called,
which clears `paused=0` and calls `publish_order_to_registry`. This is the mechanism
used in the e2e test to assert registry non-visibility (stage 03) before controlled
publication (stage 04).

Both flags are checked at the top of `start_sync_negotiation()` in
`sync_negotiation.py`, raising `StorefrontPausedError` which the negotiate
endpoint converts to HTTP 503.

#### Negotiation Detail Response Shape

`GET /api/v1/listings/{listing_id}/negotiations/{neg_id}` returns the full
buyer↔seller conversation in one call (no DB access required from callers):

```json
{
  "negotiation_id": "neg_abc",
  "our_listing_id": "listing_xyz",
  "their_agent_id": "0xBuyerAddress",
  "terminal_state": "success",
  "agreed_price": 9000,
  "round_count": 4,
  "messages": [
    {"round": 0, "sender": "0xBuyer", "action_taken": "make_offer", "proposed_price": 7000},
    {"round": 1, "sender": "http://seller:8001", "action_taken": "counter_offer", "proposed_price": 9500},
    {"round": 2, "sender": "0xBuyer", "action_taken": "counter_offer", "proposed_price": 8500},
    {"round": 3, "sender": "http://seller:8001", "action_taken": "accept_offer", "proposed_price": 9000}
  ],
  "stage_events": [...]
}
```

No new DB state — reads `negotiation_threads`, `negotiation_messages`, and
`stage_events` tables.

---

### `buyer` (Pure HTTP client)

**Role:** The buyer side of the market. There is no buyer server, no
agent runtime, no SQLite database — only the `market` console script
(package: `buyer/`, import: `market_buyer`).

`market buy` is a one-shot orchestrator: it queries
`registry-service` for matching seller orders, runs synchronous
negotiations against each candidate seller's storefront (POST
`/negotiate`, signed bodies), and on agreement creates the on-chain
escrow via `alkahest_py` directly from the CLI process before POSTing
`/settle/{escrow_uid}` and polling for fulfillment. `market negotiate`
is the same loop bound to a single known seller; both share
`buy_orchestrator`.

The negotiation policy used by the buyer is the same `market-policy`
engine the seller runs — both sides import a `BisectionStrategy` (or,
behind the `[rl]` extra, the trained Arkhai pufferlib checkpoint)
through `market_policy.negotiation_strategy`. Round-by-round events
land in a per-run JSONL log under
`$XDG_STATE_HOME/arkhai/buy-runs/<run_id>.jsonl` rather than a
database.

**Key source layout:**
```
buyer/market_buyer/
├── cli.py                  # `market` console-script entry
├── groups/                 # buy, negotiate, order, config, logs, escrow, network
├── buy_orchestrator.py     # the one-shot buy flow
├── buyer_client.py         # signed HTTP client for /negotiate
├── escrow_client.py        # alkahest-py escrow create/reclaim
├── run_log.py              # JSONL run logs under XDG_STATE_HOME
└── common.py               # config-resolution + REPO_ROOT helpers
```

---

### `policy` (`market-policy`)

Domain-agnostic strategy engine + training tool. Two surfaces:

- **Library**: `market_policy.{store, manager, registry, evaluator,
  composite, negotiation_thread, negotiation_strategy,
  action_builders, identity}` — imported by both runtimes.
- **CLI**: `market-policy train / eval / export` — invoked by
  policy authors to produce strategy artifacts (RL checkpoints) that
  buyers and sellers load at runtime through
  `market_policy.negotiation_strategy.load_strategy()`.

The CLI lives here (not in either runtime) because policy authoring
is a tooling concern separate from the buyer or seller process.

---

### `provisioning-service`

**Role:** Physical settlement layer. Converts completed on-chain agreements into running VMs.

A unified single-process service: the FastAPI app and the background job processing loop run together in one uvicorn process.

```
Agent ──HTTP──▶ Provisioning API :8081
                      │         │
                      │    asyncio.Queue (in-process)
                      │         │
                      └── job DB (SQLite/Postgres)
                                │
                         Job Processing Loop
                                │
                         ansible-playbook──▶ KVM host
```

Long-running Ansible playbooks (up to `ANSIBLE_TIMEOUT_SECONDS=1800`) are launched as non-blocking subprocesses via `asyncio.create_task`. The event loop stays responsive to new requests while playbooks run. Up to `max_concurrent_jobs` (default 5) jobs run in parallel, controlled by an `asyncio.Semaphore`. The in-process `asyncio.Queue` replaces the former Redis queue; the service has no external queue dependency.

#### Service layer architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Controllers (FastAPI layer)                                │
│  VmController, HostController, JobController (read-only)    │
│  Accepts typed per-operation requests                       │
│  Returns job_id; OpenAPI docs describe polling pattern      │
└─────────────────────────┬───────────────────────────────────┘
                          │ AnsibleJobParams (internal DTO)
┌─────────────────────────▼───────────────────────────────────┐
│  AnsibleJobService                                          │
│  - submit(AnsibleJobParams, agent_id, job_queue) → job_id   │
│  - list/get/cancel/credentials/logs (read ops)              │
│  - _process_job(job_id) — handler passed to AsyncJobQueue   │
└──────────────┬──────────────────┬──────────────────────────┘
               │ handler dispatch │ direct call
┌──────────────▼──────┐  ┌───────▼──────────────────────────┐
│  AsyncJobQueue      │  │  AnsibleService                  │
│  (queue mgmt only)  │  │  - start_playbook()              │
│  - enqueue(job_id)  │  │  - wait_for_playbook()           │
│  - start(handler)   │  │  - build_vars_file()  ← absorbed │
│  - is_alive()       │  │  - parse_playbook_result() ←     │
│  No Ansible/DB      │  │  - _inject_golden_image_creds()  │
│  knowledge          │  │  - parse_inventory()             │
└─────────────────────┘  │  - lookup_host_ip()              │
                         │  - check_connectivity()          │
                         └──────────────────────────────────┘
```

---

#### Job Lifecycle

Jobs are tracked in the `ansible_jobs` database table. Status transitions:

```
queued ──▶ running ──▶ succeeded
                  └──▶ failed (retryable) ──▶ queued (re-enqueued with backoff)
                  └──▶ failed (permanent, or max retries exceeded)
queued ──▶ cancelled  (by API call before worker picks it up)
running ──▶ cancelled (SIGTERM sent to ansible-playbook PID, stored in job.process_id)
```

**Retry behavior:** Failed jobs are retried with exponential backoff (`initial=60s`, `multiplier=2x`, `max=3600s`) up to `max_retries` (default 3, caller-overridable per job up to 10). Certain errors are non-retryable and short-circuit immediately: SSH auth failures, host unreachable, domain not found, disk image lock conflicts, and others defined in `config.non_retryable_errors`.

**Job DB fields of operational interest:**

| Field | Meaning |
|---|---|
| `status` | `queued / running / succeeded / failed / cancelled` |
| `params` | Full JSON of the original `ProvisionRequest` |
| `result` | Structured JSON from Ansible on success (SSH info, VM name, GPU, FRP, resources, etc.) |
| `error` | Error string on failure, including retry scheduling info |
| `logs` | Raw Ansible stdout+stderr, updated every ~2s while running; credentials redacted |
| `process_id` | PID of the running `ansible-playbook` subprocess — useful for host-level inspection |
| `retry_count / max_retries / next_retry_at` | Retry state |
| `agent_id` | ERC-8004 ID of the seller who submitted the job |
| `buyer_agent_id` | ERC-8004 ID of the buyer (tenant) — controls credential visibility |

**Credentials** are stored separately in the `credentials` table (joined to job by `job_id`), split by role:
- `root` — granted to seller only; includes root password and SSH key path on host
- `tenant` — granted to both seller and buyer; includes tenant password and SSH commands (internal + external via FRP)

---

#### VM Actions (all routed through a single playbook: `vm-operations.yaml`)

All actions are submitted as `ProvisionRequest` jobs with a `vm_action` field. The single Ansible playbook dispatches to action-specific task files based on the `vm_action` variable.

| `vm_action` | What it does | Notable behavior |
|---|---|---|
| `create` | Provision a new KVM VM | Writes a cleanup script to `/usr/local/bin/cleanup_vm_<name>.sh` on the host; configures FRP tunnel; optionally attaches GPU passthrough |
| `list` | List all VMs on the host | No `vm_target` required |
| `start` | Start a stopped VM | |
| `shutdown` | Graceful ACPI shutdown | |
| `destroy` | Force-kill a running VM | Does not remove storage or definition |
| `reboot` | Reboot a running VM | |
| `undefine` | Remove VM definition from libvirt | Typically paired with storage cleanup |
| `monitor` | Collect CPU/memory/disk/network stats | See details below |
| `reset_password` | Reset the tenant user password | |
| `lease_end` | Schedule VM destruction at a future UTC datetime | Uses the host's `at` daemon — **the timer runs on the KVM host, not in the provisioning service** |
| `lease_remove` | Cancel a previously scheduled `lease_end` | Finds and removes `at` jobs tagged `LEASE:<vm_name>` |
| `check` | Report host capacity (total/allocated/available vCPUs, RAM, GPUs) | No `vm_target` required |

---

#### Lease Lifecycle — the key design gap

**The lease expiry is not monitored by the provisioning service.** The `lease_end` action schedules a shell command with the Unix `at` daemon on the KVM host itself. At the scheduled UTC time, `at` runs:

1. `virsh destroy <vm_name>` (force-kill)
2. `/usr/local/bin/cleanup_vm_<vm_name>.sh` — a script written to the host during `vm-create` that removes FRP config, iptables rules, UFW/firewalld rules, GPU detachment, static DHCP lease, SSH keys, cloud-init files, VM storage, and VM definition

**Nothing in the provisioning service polls for lease expiry or triggers `lease_end` automatically.** The agent is expected to call `lease_end` (via a provisioning job) when the on-chain agreement's duration expires. This means:

- If the agent crashes or loses its state before calling `lease_end`, the VM runs forever unless the operator intervenes manually
- The only record of whether cleanup ran is the log file on the KVM host at `/var/log/vm-lease-end/<vm_name>/lease_end_*.log`
- The provisioning service has no visibility into whether the `at` job actually executed

**`lease_remove`** is the cancel operation — it cancels a pending `at` job before it fires. Once the `at` time has passed and the job has run, `lease_remove` will find no matching job (it searches `atq` for `LEASE:<vm_name>` tag) and fail.

---

#### `monitor` action — what it returns

`monitor` runs a series of `virsh` commands against the named VM on the target host and returns structured JSON. Fields returned via the job's `result.resources`:

- `cpu.usage_percent` — calculated from two `virsh domstats` samples 1 second apart
- `cpu.vcpus_provisioned`
- `memory.used_mb`, `memory.available_mb`, `memory.usage_percent`
- `storage.allocation_gb`, `storage.capacity_gb`, `storage.usage_percent` — host-side view via `virsh domblkinfo`
- `storage.guest_total/used/available` — guest-side via `virsh domfsinfo` (requires `qemu-guest-agent` installed in VM; returns N/A if not)
- `network_interfaces` — list of interface names found via `virsh domiflist`

`monitor` fails if the VM doesn't exist or isn't in `running` state.

**`monitor` is not called automatically.** Nothing in the codebase polls `monitor` on a schedule. It must be submitted as an explicit provisioning job.

---

#### `check` action — host capacity

`check` (no `vm_target` required) reports total vs. allocated vs. available resources on a KVM host:
- vCPUs: physical cores via `nproc` vs. sum of vCPUs across all running VMs
- RAM: from `/proc/meminfo` vs. sum of `Max memory` across running VMs
- GPUs: counts NVIDIA/AMD GPU PCIe functions (`.0` only) via `lspci`, checks which are attached to VMs via `virsh dumpxml`

Useful for pre-flight capacity checking before a `create` job.

---

#### Provisioning API Endpoints (`main.py` / `api/routes.py`, port `8081`)

- `GET  /health` — checks API, database connectivity, and job processing loop liveness; returns `{"status": "ok"|"degraded", "checks": {...}}`
- `POST /jobs` — submit a provisioning job; returns `{"job_id": "...", "status": "queued"}`; accepts `X-Agent-ID` header (required when auth is enabled)
- `GET  /jobs` — list jobs with pagination (`offset`/`limit`), status filter, sort; authenticated agents see only their own jobs (seller or buyer role)
- `GET  /jobs/{job_id}` — full job status including params, result, error, and retry metadata
- `GET  /jobs/{job_id}/credentials` — returns credentials for the requesting agent; **requires `X-Agent-ID` header always** (regardless of `ENABLE_AUTH`); sellers get root+tenant, buyers get tenant only
- `GET  /jobs/{job_id}/logs` — raw Ansible stdout+stderr for the job; credentials are redacted in storage but paths/keys may appear; logs update in near-real-time while job is running
- `POST /jobs/{job_id}/cancel` — cancels a queued job, or sends `SIGTERM` to the Ansible PID if the job is running

#### Ansible Diagnostic Endpoints (unified API, port `8081`)

Previously a separate worker admin API on port 8082; now folded into the main API under `/api/v1/ansible/`.

- `GET /health` — checks API, database, and job processing loop liveness
- `GET /inventory` — parses the Ansible INI inventory file and returns all hosts with their `ansible_host` values and inline vars; supports `?search=<substring>` for hostname filtering
- `GET /inventory/{host}/connectivity` — runs `ansible -m ping` against a single named host, exercising the complete auth path (inventory parse → SSH key → Ansible execute); returns `{"reachable": true/false, "detail": "..."}` — returns HTTP 200 either way, only 404 if host not in inventory

---

#### Operational Visibility — what you can see and where

| Question | Where to look |
|---|---|
| Is the provisioning service healthy? | `GET /health` (API) and `GET /health` (worker admin) |
| What jobs exist and their statuses? | `GET /jobs?status=<filter>` |
| Why did a job fail? | `GET /jobs/{id}` (error field) + `GET /jobs/{id}/logs` (raw Ansible output) |
| Is Ansible able to reach the KVM host? | `GET /inventory/{host}/connectivity` (worker admin) |
| What VMs exist on the host? | Submit a `list` job, check `result` when succeeded |
| What resources are available on the host? | Submit a `check` job |
| What are the resource usage stats for a running VM? | Submit a `monitor` job |
| Did the lease-end cleanup actually run? | SSH to KVM host: `cat /var/log/vm-lease-end/<vm_name>/lease_end_*.log` — no API visibility |
| What `at` jobs are pending on the host? | SSH to KVM host: `atq` — no API visibility |
| Is a VM stuck in `running` state in Ansible mid-job? | `GET /api/v1/jobs/{id}` — `process_id` field gives the Ansible PID (same container as the API) |

---

**Key source layout:**
```
provisioning-service/src/
├── controllers/                # Handles Http Routing concerns.
├── services/                   # For internal business logic
├── models/                     # Request and Response objects for controllers
├── middleware/
│   ├── auth.py                 # AgentAuthMiddleware (ERC-8004 X-Agent-ID enforcement)
│   └── rate_limit.py           # AgentRateLimitMiddleware (sliding window per agent)
├── db/
│   ├── models.py               # AnsibleJob + Credential SQLAlchemy models (table: ansible_jobs)
│   └── database.py
├── config/
│   ├── config.yml              # Environment schema (mostly empty — structure documentation)
│   ├── config-docker.yml       # IaC paths + ansible_cfg for standalone container runs
│   └── config-local.yml.example  # Developer override template (copy to config-local.yml)
├── container.py                # dependency-injector DeclarativeContainer
├── config.py                   # Profile-aware dynaconf loader
├── settings.toml               # Committed base defaults
└── main.py                     # FastAPI app + lifespan (starts job processing loop)
```

---

#### Configuration System

The provisioning service uses a profile-based configuration system. Resolution order (highest priority first):

1. `PROVISIONING_*` environment variables — last-resort escape hatch only
2. `config/config-<profile>.yml` files (one per entry in `ACTIVE_PROFILES`)
3. `config/config.yml` (environment schema — mostly empty, documents structure)
4. `settings.toml` (committed base defaults)

**Available profiles:**
- `local` — developer overrides; copy `config/config-local.yml.example` to `config/config-local.yml` (gitignored) and set `ACTIVE_PROFILES=local` in `.env`
- `docker` — baked into the image via `ENV ACTIVE_PROFILES="docker"`; supplies IaC paths and `ansible_cfg` for standalone container runs
- `production` — used in Kubernetes; rendered from Helm `values.yaml` into a ConfigMap mounted at `CONFIG_DIRECTORY`
- `provisioning-secrets` — used in Kubernetes alongside `production`; rendered from a Helm Secret into `config-provisioning-secrets.yml` mounted at `CONFIG_DIRECTORY`. Carries sensitive keys that must not appear in a ConfigMap plaintext (`ssh_decryption_key`, `inventory_ini`).
- `mock` — initializes `MockAnsibleService` with deterministic fake results and no subprocess calls. Intended for docker-compose and e2e tests where no real KVM hardware is available.

**Helm configuration policy — all config travels through the profile system:**

Pods set only `ACTIVE_PROFILES` and `CONFIG_DIRECTORY` as environment variables. All application settings travel through mounted ConfigMap or Secret files, never as individual `env` entries in the pod spec. This rule applies equally to the application Deployment and to helm test pods.

The reasoning: environment variables are the highest-priority override layer in dynaconf. Injecting individual settings as env vars silently overrides anything an operator configures in a profile file, defeating the purpose of the profile system. The only acceptable env vars on a pod are the profile resolver variables (`ACTIVE_PROFILES`, `CONFIG_DIRECTORY`) and the subprocess-required `ANSIBLE_CONFIG`.

**Pattern for secrets in Kubernetes:**

Secrets that cannot be placed in a ConfigMap (key material, sensitive credentials) are stored as a Kubernetes Secret whose data contains a `config-<profile>.yml` key. The Secret is mounted as a volume at `CONFIG_DIRECTORY`; the profile name is added to `ACTIVE_PROFILES`. This is identical to the ConfigMap approach — the dynaconf loader sees no difference between a file mounted from a ConfigMap and one mounted from a Secret.

Example — the provisioning-secrets profile:
```
Secret data key:  config-provisioning-secrets.yml
Mount path:       /app/config/config-provisioning-secrets.yml
ACTIVE_PROFILES:  production,provisioning-secrets
```

The same pattern applies to helm test pods. The shared `test-config` ConfigMap provides non-secret values (service URLs, feature flags) merged by the `helm` profile. Test pods that need secret material mount an additional Secret volume as a second profile.

**Why `ENV` vars are not used for application config:**

Environment variables are the highest-priority override layer. Baking application config into `ENV` instructions in a Dockerfile means any operator trying to change a value via a profile file is silently overridden — the opposite of the intended behaviour. The Dockerfile therefore only sets `ACTIVE_PROFILES` and `CONFIG_DIRECTORY`.

The one exception is `ANSIBLE_CONFIG`: this is consumed by the `ansible-playbook` subprocess via `os.environ` rather than by Python code, so it cannot travel through dynaconf. It is read from `settings.ansible_cfg` at lifespan startup and written to `os.environ` before the first playbook run.

**Helm ConfigMap approach:**

The Helm chart renders the entire `config:` block from `values.yaml` directly into `config-production.yml` using `{{ .Values.config | toYaml }}`. Adding a new non-secret config key requires only a `values.yaml` change — no Deployment template changes needed. Secret keys go into the `sshDecryptionKey` Secret block in `values.yaml`, which renders into `config-provisioning-secrets.yml`.

---

#### Ansible Inventory and SSH Key — How They Are Provided at Runtime

There are three distinct inputs the provisioning service needs from outside the container. Before documenting them, a terminology clarification that the codebase conflates:

**Ansible inventory vs. KVM hosts — these are different things:**

- **Ansible inventory** — an INI file telling Ansible *how to connect* to machines: aliases, IPs, SSH users, key paths, and group memberships. In the implemented design this is a *rendered artifact* produced from the `hosts` DB table immediately before each playbook run, not a file maintained on disk.

- **KVM/libvirt host** — a bare-metal machine running the KVM hypervisor and `libvirt` daemon. Libvirt's own state lives on each machine in `/etc/libvirt/` and is managed via `virsh`. The provisioning service never talks to libvirt directly — Ansible SSHes into the KVM machine and runs `virsh` commands there.

---

**1. SSH private key** (`~/.ssh/id_ed25519`)

The provisioning service authenticates Ansible SSH connections using keys stored per host in the `hosts` table. Two key storage modes are supported:

- **`path`** — `ssh_key_value` is a filesystem path (e.g. `/home/appuser/.ssh/id_ed25519`). The default Helm chart mounts the operator's key at this path via a Kubernetes Secret volume. Hosts sharing the same physical key all reference the same path.
- **`embedded`** — `ssh_key_value` stores Fernet-encrypted PEM key material in the database. Requires `ssh_decryption_key` delivered via the `provisioning-secrets` config profile. At job execution time `AnsibleService.write_inventory()` decrypts the key and writes it to a temp file alongside the rendered inventory; both are cleaned up in the `finally` block.

The Dockerfile uses a direct `CMD ["uvicorn", ...]` entrypoint.

---

**2. Golden image credentials**

Golden image credentials (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`, `golden_gcs_bucket`, `golden_gcs_project`) are first-class keys in `settings.toml` and the config profile system.

- **Locally** — set in `config/config-local.yml`
- **In Kubernetes** — set in the `config:` block of Helm `values.yaml`; rendered into `config-production.yml` by the ConfigMap

---

**3. Host registry**

The `hosts` DB table is the single source of truth for KVM host inventory. The Ansible INI file is an *input format only* — it is never read at runtime except as input to `POST /hosts/import` or the `inventory_ini` startup seeder.

**`hosts` table columns:** `name` (PK, Ansible alias), `kvm_host` (IP), `ssh_user`, `ssh_key_type` (`"path"` | `"embedded"`), `ssh_key_value`, `gpu_count`, `enabled`, `created_at`, `updated_at`.

**Column naming:** `kvm_host` and `ssh_user` — decoupled from Ansible's own variable names (`ansible_host`, `ansible_user`). Ansible variables are only introduced when the INI is rendered for a playbook run.

**REST API:**
```
GET    /api/v1/hosts/               List enabled hosts (DB query)
POST   /api/v1/hosts/               Register a host (JSON body)
POST   /api/v1/hosts/import         Bulk-import from Ansible INI block (upsert, append-only)
GET    /api/v1/hosts/{host}         Host details
PUT    /api/v1/hosts/{host}         Update connection details
POST   /api/v1/hosts/{host}/enable  Re-enable a disabled host
POST   /api/v1/hosts/{host}/disable Soft-delete (sets enabled=False)
GET    /api/v1/hosts/{host}/capacity       Submit capacity check job
GET    /api/v1/hosts/{host}/connectivity   Run ansible -m ping
```

**Upsert / append-only semantics:** `POST /hosts/import` upserts rows — hosts present in the INI are inserted or updated; hosts absent from the INI are never disabled or removed. This preserves job history FK integrity (jobs reference `vm_host` by name string).

**Disable vs. delete:** There is no hard delete endpoint. `POST /hosts/{host}/disable` sets `enabled=False`. Disabled hosts are excluded from `GET /hosts/` (default) and from inventory rendering.

**Inventory rendering for Ansible:** `AnsibleService.write_inventory(hosts)` renders a temp INI file from DB rows immediately before each playbook run, deleted in the `finally` block — the same contract as `build_vars_file`. The rendered group is always `[kvm_hosts]`.

**Inventory seeding at startup:** `main.py` seeds the hosts table once during lifespan startup using the following logic:

- **Skip if the table is non-empty.** If any hosts are already registered (from a previous startup or via the API), seeding is skipped entirely. Operator changes made through the API are never overwritten on pod restart. To force a re-import, use `POST /api/v1/hosts/import` which always upserts regardless of table state.
- **Source 1 — `inventory_ini` setting** (Helm/Kubernetes): the `provisioning-secrets` config profile carries this value. Used when deploying via Helm.
- **Source 2 — `inventory_path` on disk** (Docker): the `docker` config profile sets `inventory_path` to the IAC hosts file baked into the image. Used when running the container standalone without a Helm-injected INI.

**`[kvm_hosts]` group only:** `_parse_ini` imports only entries under the `[kvm_hosts]` INI group. Other groups in the IAC inventory (e.g. `[frp_servers]`, `[provisioning_servers]`) describe infrastructure that manages the provisioning service itself and are not relevant to VM provisioning.

**`gpus=` variable mapping:** The IAC inventory uses `gpus=N` to declare GPU count. `_parse_ini` maps this to the `gpu_count` column. `ansible_ssh_private_key_file=` is stored verbatim as the key path. All other Ansible variables are ignored.

**`SystemService.ansible_readiness`** reads host count and SSH key diagnostics from the `hosts` DB table. `SshKeyInfo` has a `key_type` field: `path`-type hosts have their key file stat'd and SHA-256'd; `embedded`-type hosts report `exists=True` with no SHA-256 (key is encrypted at rest).

---

### `compute-provisioning-iac` (submodule)

**Role:** Infrastructure-as-code for the physical layer. A git submodule.

Contains Ansible roles and Terraform modules used by both the provisioning worker (at runtime) and operators (to set up seller hardware).

**Ansible roles:**
- `vm-setup` — prepares a KVM host: GPU passthrough, KVM networking, golden image build (Packer + Ubuntu Noble), FRP client config, security hardening
- `vm-management` — day-2 VM operations: create/destroy/start/stop, GPU assignment, lease management
- `frp-setup` — sets up FRP server (fast reverse proxy) for buyer network access to VMs
- `docker-app` — deploys Docker-based apps to a host

**Terraform modules:** GCP-focused (Cloud Run, artifact registry, service accounts, Redis, ZeroTier controller). Used for the production/staging/sandbox cloud deployment of the non-hardware services.

**TODO:** Document the GPU passthrough setup and any constraints on host hardware.

---

#### FRP Topology — How Buyers Reach Their VMs

FRP (Fast Reverse Proxy) is the network access mechanism that allows a buyer to SSH into a provisioned VM without the seller's KVM host being publicly addressable. It is optional — the playbook falls back to direct port forwarding when `frp_server_addr` is not provided — but it is the intended production path.

**The three machines involved:**

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  FRP Server  (separate public VPS, not the KVM host) │
│  Runs: frps (FRP server daemon)                      │
│  Ports: 7000 (control), 7002–8000 (proxy range)     │
│  Domain: frp-admin.<domain>  (Nginx + TLS)           │
│  Dashboard: port 7001, localhost-only                │
└──────────────┬──────────────────────────────────────┘
               │  persistent TLS tunnel (port 7000)
               ▼
┌─────────────────────────────────────────────────────┐
│  KVM Host  (seller's bare-metal machine)             │
│  Runs: frpc (FRP client daemon), libvirt, VMs        │
│  frpc config: /etc/frp/frpc.toml                    │
│  One [[proxies]] block added per VM at create time   │
└──────────────┬──────────────────────────────────────┘
               │  internal KVM bridge network
               ▼
┌─────────────────────────────────────────────────────┐
│  Guest VM  (tenant's compute, private IP)            │
│  SSH port 22 — not directly reachable               │
└─────────────────────────────────────────────────────┘
```

**How the FRP server is deployed:**

The `frp-setup` Ansible role, invoked via `playbooks/frp/frp-server-setup.yaml` targeting the `[frp_servers]` inventory group, configures a standalone public VPS as the FRP server. This is a one-time operator setup step, separate from the provisioning service's job flow. The role:

- Installs `frps` as a systemd service
- Configures token-based auth (`auth.token`) and TLS
- Opens the port range `7002–8000` for proxy connections via UFW
- Installs Nginx to reverse-proxy the FRP dashboard (`port 7001`, localhost-only) to `https://frp-admin.<domain>` with a Let's Encrypt certificate
- Saves the generated `auth_token` and `dashboard_password` to a local credentials JSON file for use when provisioning VMs

**How the KVM host gets its FRP client:**

The `vm-setup` Ansible role (host preparation, not per-VM) installs `frpc` as a systemd service on the KVM host with a base `frpc.toml` pointing at the FRP server. At this stage the config has no proxy entries — it just establishes the persistent control connection to the FRP server.

**What happens at VM creation:**

When a `create` job runs with `frp_server_addr` set, the playbook:

1. Queries the FRP dashboard API (`https://frp-admin.<domain>/api/proxy/tcp`) to find existing proxy names and allocate a unique 6-character subdomain suffix for the new VM.
2. Queries the same API to find an unused port in the `7002–8000` range for the VM's remote port.
3. Appends a new `[[proxies]]` block to `/etc/frp/frpc.toml` on the KVM host (using Ansible `blockinfile` with a marker comment `# ANSIBLE MANAGED BLOCK FOR VM <vm_name>`):
   ```toml
   [[proxies]]
   name = "vm-<subdomain>"
   type = "tcp"
   localIP = "<vm_internal_ip>"
   localPort = 22
   remotePort = <allocated_port>
   subdomain = "<subdomain>"
   transport.useEncryption = true
   ```
4. Restarts `frpc` to pick up the new entry.

The FRP server then accepts connections on `<remotePort>` and tunnels them through the persistent KVM host connection to the VM's internal SSH port 22.

**What the buyer receives:**

The `vm_creation_data` JSON returned by the playbook (and stored in `job.result`) contains two SSH access modes depending on whether FRP was used:

| Field | FRP mode | Direct port-forward mode |
|---|---|---|
| `frp.enabled` | `true` | `false` |
| `frp.remote_port` | allocated port (e.g. `7045`) | N/A |
| `frp.subdomain` | e.g. `a3b9f2` | N/A |
| `frp.domain` | e.g. `arkhainet.whitewidget.tech` | N/A |
| `authentication.tenant.ssh_commands.external` | `ssh -i <key> -p 7045 vmname@a3b9f2.arkhainet.whitewidget.tech` | `ssh -i <key> -p <port> vmname@<kvm_host_ip>` |
| `authentication.tenant.ssh_commands.internal` | `ssh -i <key> vmname@<vm_internal_ip>` | same |

The provisioning client (`service/clients/provisioning.py`) normalizes the result and substitutes `frp.domain` as `vm_host_ip` when FRP is active, so the rest of the agent code sees a consistent connection-details shape regardless of mode.

**VM teardown and FRP cleanup:**

The cleanup script written to `/usr/local/bin/cleanup_vm_<name>.sh` on the KVM host at create time includes removal of the FRP proxy block (sed delete on the `ANSIBLE MANAGED BLOCK FOR VM <name>` markers in `frpc.toml`) and a `frpc` restart. This runs as part of the `at`-scheduled lease expiry. The FRP server retains no persistent state — the proxy entry disappears as soon as `frpc` reconnects without it.

**Fallback mode (no FRP):**

When `frp_server_addr` is not provided in the create request, the playbook instead:
- Picks a random unused port in the range `10000–65000` on the KVM host
- Adds an iptables `PREROUTING` DNAT rule forwarding `<kvm_host_ip>:<port>` → `<vm_internal_ip>:22`
- Opens the port via UFW/firewalld
- Returns `<kvm_host_ip>` and `<port>` as the external SSH coordinates

This mode requires the KVM host to have a publicly reachable IP, which is not always the case and exposes the host's public IP to buyers.

**Operational notes:**

- The FRP server is infrastructure the seller operator must provision and maintain separately — it is not deployed or managed by the provisioning service's job system.
- The `frp_server_addr`, `frp_domain`, and `frp_dashboard_password` are passed into every `create` job (either per-request or from the provisioning service's config defaults `FRP_SERVER_ADDR`, `FRP_DOMAIN`, `FRP_DASHBOARD_PASSWORD`). They are seller-global values in the current design.
- The FRP dashboard at `https://frp-admin.<domain>` shows all active proxy connections — this is currently the only way to get a live view of which VMs have active tunnels, since the provisioning service has no VM state table. This is another facet of the visibility gap described in TODO item 4.

---

### CLIs

There are four console scripts, each a separate distributable. They
split by concern (runtime vs. tooling vs. operator infra) rather than
by buyer-vs-seller role. Built with Typer; config is read from a
single TOML file at `$XDG_CONFIG_HOME/arkhai/config.toml` (override
with `--config <path>`).

| CLI | Package | Role | Top-level groups |
|---|---|---|---|
| `market` | `buyer/` | Buyer runtime (pure HTTP client) | `buy`, `negotiate`, `order`, `escrow reclaim`, `network join/get-peers`, `config`, `logs` |
| `market-storefront` | `storefront/` | Seller runtime | `register`, `serve`, `provide`, `escrow claim/refund`, `portfolio import-csv`, `network join/get-peers`, `config`, `logs` |
| `market-policy` | `policy/` | Policy authoring tool | `train`, `eval`, `export` |
| `market-infra` | `infra/` | Market-operator infra (one process per market) | `chain up/deploy-contracts`, `registry start`, `network install/create/add` |

The two runtimes (`market`, `market-storefront`) share `network join`
and `get-peers` because each operator manages their own ZeroTier
membership. The owner-side actions (`install` / `create` / `add`)
live in `market-infra` because they are run once per market by the
trust authority, not per-agent.

Deployment shells just compose CLI verbs:

- **Docker (storefront image):** `entrypoint.sh` brings up the
  ZeroTier daemon, then runs `market-storefront register` and
  `exec market-storefront serve`.
- **Helm:** the init container runs
  `./entrypoint.sh market-storefront register --chain-id N` and the
  main container runs `./entrypoint.sh market-storefront serve` —
  same image, two CLI verbs.

See `docs/cli-redesign-plan.md` for the rationale and migration
table behind the current 4-CLI surface.

---

## Deployment Topology

### Local Dev (compose)

```
compose/market.yml   — test-env (Anvil) + registry-service
compose/seller.yml   — storefront server + provisioning service (unified)
compose/external.yml — (unclear — TODO)
```

There is no `compose/buyer.yml` anymore — the buyer is the `market`
CLI invoked from the host or another container, not a long-running
service. The seller container reads its config from a TOML file
mounted at `/etc/arkhai/config.toml` (set via `XDG_CONFIG_HOME=/etc`);
the `.env` flow used by the previous symmetric topology has been
retired.

### Production / Staging — Helm (`helm/`)

The intended production deployment path is a single Helm umbrella chart named `arkhai-node-operator` located at `helm/`. It manages all runtime services as conditional subcharts and is the target for `helm upgrade --install`.

**Chart structure:**
```
helm/
├── Chart.yaml              # Umbrella chart; declares subchart dependencies
├── values.yaml             # Single source of truth for all configuration
├── _helpers.tpl
├── Makefile                # init, template, deploy, test, forward/unforward
├── templates/
│   └── tests/test-config.yaml  # Shared ConfigMap for helm test pods
└── charts/
    ├── test-env/           # Anvil node (condition: test-env.enabled)
    ├── registry/           # registry-service (condition: registry.enabled)
    ├── storefront/         # storefront-service (condition: agents>0)
    ├── provisioning/       # Unified provisioning service (condition: provisioning.enabled)
    └── validate-contracts/ # Helm test: chain connectivity check
```

**Kubernetes objects deployed:**

| Subchart | Deployments | Services |
|---|---|---|
| `test-env` | 1 (Anvil) | 1 NodePort :8545 |
| `registry` | 1 | 1 NodePort :8080 |
| `storefront` | 1 | 1 NodePort :8001 |
| `provisioning` | 1 (unified API + job loop) | 1 ClusterIP (:8081) |

**Startup ordering** is enforced by init containers:
- The seller agent waits on RPC (`eth_blockNumber` poll) and registry (`/health` poll) before starting
- The provisioning container has no init containers or startup dependencies
- The test-env container has no init containers or startup dependencies

**Secrets:**
- Seller agent private key + wallet address → `Secret` per agent, sourced from `values.yaml` `secret.privKey` / `secret.walletAddress`, or an externally pre-created secret
- SSH private key for Ansible → `Secret` mounted as a volume at `/home/appuser/.ssh/id_ed25519` (mode 0400); set via `--set-file provisioning.sshKey.sshPrivateKey=$(SSH_KEY_FILE)` at deploy time or by providing a pre-existing Secret

**Global values** propagated to all subcharts:
- `global.imageRepository` — optional registry prefix for all images
- `global.rpc.{host,port,chainId}` — single source of truth for the Anvil/chain coordinates
- `global.registry.{host,port,identity_address,...}` — registry service coordinates and contract addresses
- `global.provisioning.{host,port}` — provisioning service coordinates

**Helm Makefile targets:**
```
make init              # helm dependency update
make template          # render full chart to stdout (dry-run)
make template-module MODULE=<subchart>   # render a single subchart
make deploy            # helm upgrade --install (SSH_KEY_FILE=~/.ssh/id_ed25519)
make test              # helm test --logs (runs all test pods)
make test-module MODULE=<subchart>       # run tests for one subchart
make forward           # kubectl port-forward all services to localhost
make unforward         # kill all port-forwards
```

**Port-forward map** (local dev against a deployed cluster):
```
localhost:8545  → test-env (Anvil RPC)
localhost:8080  → registry
localhost:8001  → seller storefront
localhost:8081  → provisioning API (also handles ansible inventory + connectivity endpoints)
```

**Helm test suite:**
- `validate-contracts` — verifies RPC connectivity and contract deployment by running `pytest -m contracts` against the integration test image
- `registry` — environment smoke test
- `storefront` — environment smoke test
- `provisioning` — environment smoke test (no provisioning test pod currently defined in source)
- All tests share a ConfigMap (`{release}-test-config`) injected as `config-helm.yml`, containing resolved RPC URLs, contract addresses, and agent URLs

**Notable gaps / fitness questions to investigate:**
- No `PersistentVolumeClaim` for agent SQLite DBs — each pod restart loses negotiation history and policy state (significant given the known SQLite statefulness issues)
- No `PersistentVolumeClaim` for registry SQLite — event sync state is also ephemeral
- Agent `Deployment` has no liveness or readiness probes (noted as TODO in the template)
- Agent ID persistence across pod restarts is handled by `seller.onchain_agent_id` in config (a Helm value). On first deploy with `agentId: ""` and `autoRegister: true`, the service registers and logs the assigned ID. Operators pin that ID in `values.yaml` and flip `autoRegister: false` to prevent accidental re-registration. The compose flow (which used `ONCHAIN_AGENT_ID=` env var clearing to force re-registration on fresh Anvil) is unchanged.
- `test-env.enabled: true` in the default values — in production this needs to be `false` and `global.rpc.*` overridden to point at a live chain
- `replicaCount` exists for the storefront and provisioning API but running multiple replicas of either without shared persistent storage would be incorrect

---

## Build & Init Flow

```
make build
  ├── build-cli                  # PyInstaller → cli/dist/market
  ├── build-market-contract-deployer
  ├── build-test-env
  │     └── build-anvil-state   # Runs deployer against fresh Anvil, saves state.json
  └── build-runtime-images (parallel)
        ├── build-registry       # registry-service Docker image
        ├── build-core           # core Docker image
        └── build-provisioning   # async-provisioning-service Docker image
```

---

## Known Issues & Areas of Concern

> This section should be expanded as investigation proceeds.

- **Agent SQLite statefulness:** The agent carries significant local state in SQLite (policy configs, negotiation history, resource portfolio). Behavior around container restarts, state migration, and concurrent access is a known problem area. Details TBD.

- **`ONCHAIN_AGENT_ID` clearing:** Both compose files explicitly clear `ONCHAIN_AGENT_ID=` to force re-registration on every fresh Anvil restart. This indicates the agent does not cleanly detect stale on-chain registrations on its own.

- **Negotiation orphans:** The existence of `negotiation_watchdog.py` implies negotiations can get stuck. The trigger conditions and recovery behavior need documentation.

- **`compose/external.yml`:** Purpose unclear — needs investigation.

- **`orders` → `listings` rename (partially propagated):** The SQLite table and related symbols were recently renamed from `orders` to `listings`. The rename is complete in: `sqlite_client.py` (all methods), `listings_controller.py`, `storefront-client` (models and methods), `negotiations_controller.py`. The old `orders_controller.py` was deleted. Some parts of `agent.py` and `action_executor.py` still use internal variable names like `order_id`, `created_listing_id` etc. inconsistently. The **external API URLs** (`/api/v1/listings/...`) are fully updated. The `pydantic_models.py` event class was renamed from `OrderCreateEvent` → `ListingCreatedEvent`; `EventType.ORDER_CREATE` string value is unchanged (`"order_create"`). `AcceptOfferEvent`, `MakeOfferEvent`, and `NegotiationEvent` were removed entirely; callables in `domain/compute/agent/app/policy/store.py` that depended on them are temporarily no-ops.

- **`NegotiationThreadStore` singleton in integration tests:** `NegotiationThreadTransaction` (used by `continue_sync_negotiation` → the `/negotiations/{id}/advance` endpoint) calls `get_thread_store()` on enter, which requires a one-time initialization with `sqlite_client` and `identity`. In production this happens in `TraderAgent._startup_tasks`. In integration tests the singleton must be initialized in the fixture: `import market_policy.negotiation_thread as _nt; _nt._thread_store = None; _nt.get_thread_store(sqlite_client=db, identity=Identity(agent_url="http://test-seller:8001"))`. See `test_negotiations_api.py` for the pattern.

---

## Storefront — Planned Rework

### 1. Migrate storefront HTTP layer to FastAPI

**Status:** Planned.

**Problem:** The storefront currently uses plain Starlette with manual `Request`/`JSONResponse`
throughout — in `agent.py` (20+ legacy route handlers) and in the new `controllers/`
package. The rest of the stack (provisioning-service, registry-service) uses FastAPI,
which provides:
- Automatic `/docs` Swagger UI with live request/response schemas (critical for operator
  visibility into the new orders and negotiations APIs)
- Pydantic-powered request validation with structured 422 errors instead of manual
  `if not isinstance(val, str)` checks
- Typed function parameters via `Depends()` replacing `request.path_params["x"]` extraction
- Consistency across all services — one HTTP framework to reason about

**Scope:** Both layers need to move together. Converting only the new controllers while
leaving `agent.py` on raw Starlette creates a Starlette/FastAPI hybrid that is harder
to maintain than either alone.

**Planned fix:** In a single batch:
1. Rewrite all `controllers/` to use `@router.get/post()` decorators and typed params
2. Extract all route handlers from `agent.py` into controllers (see item 2 below)
3. Replace the `Starlette(routes=[...])` app construction in `server.py` with a
   `FastAPI()` instance using `app.include_router()`
4. Replace `JSONResponse({...})` returns with plain `dict` returns (FastAPI serialises)
5. Add Pydantic request body models for the negotiate, settle, and admin endpoints

**Dependency:** Blocked on item 2 (agent.py refactor) — both should land in the same
PR to avoid an intermediate broken state.

---

### 2. Refactor agent.py routes into controllers

**Status:** Planned.

**Problem:** `agent.py` contains 20+ route handler functions defined at module level,
mixed with `TraderAgent` class definition, module-level singletons (`root_agent`,
`CONFIG`, `BASE_URL_OVERRIDE`), EIP-191 auth helpers, and background task management.
This conflation makes the handlers untestable in isolation — importing any handler
pulls in the full agent initialisation, Alkahest client setup, and SQLite connection.

The existing `tests/integration/conftest.py` documents this explicitly:
> "TODO(agent-testability): Refactor the three handler functions out of agent.py into a
> dedicated routes/ package so they can be imported and tested without triggering the
> full module-level agent initialisation."

**Planned fix:** Extract handlers into controllers following the existing `controllers/`
pattern:
```
controllers/
  negotiate_controller.py   — POST /negotiate/new, POST /negotiate/{neg_id}
  settle_controller.py      — POST /settle/{escrow_uid}, GET /settle/{escrow_uid}/status
  orders_legacy_controller.py — POST /listings/create, /close, /claim, /reclaim,
                                  /refund, /arbitrate, /discover
  alerts_controller.py      — POST /alerts/resource
  identity_controller.py    — GET /.well-known/*, GET /.well-known/agent-wallet.json
```

Each controller receives its dependencies (`sqlite_client`, `alkahest_client`,
`config`) via constructor injection rather than reading module-level globals.
This makes each handler independently importable and unit-testable.

**Dependency:** Should land in the same batch as the FastAPI migration (item 1) since
the injection pattern aligns with FastAPI's `Depends()` mechanism.

---

### 3. Storefront config unification (TOML singleton → dynaconf profiles)

**Status:** Planned.

**Problem:** The storefront uses a bespoke TOML singleton (`CONFIG` in
`market_storefront.utils.config`) loaded once at import time via a custom
`load_user_config()` / `get_dotted()` chain. This is a different system
from the profile-based dynaconf loader used by the provisioning service
and the integration test suite. The inconsistency creates friction:
- Secrets and environment-specific overrides require a separate `config.toml`
  mount rather than profile files; there is no equivalent of the
  `provisioning-secrets` profile pattern for the storefront.
- The test suite cannot inject per-test config overrides cleanly — tests
  monkeypatch `_USER_CFG` directly, which is fragile.
- Adding a new config key requires touching the `Config` dataclass, the
  `load_config()` function, and every Helm template that renders the TOML —
  three places instead of one.

**Planned fix:** Migrate the storefront config to dynaconf profiles
following the provisioning service pattern:
- Replace `load_user_config()` / `get_dotted()` with `dynaconf.Dynaconf`
  with profile resolution via `ACTIVE_PROFILES` and `CONFIG_DIRECTORY`.
- The rendered `config.toml` becomes one profile file (`config-seller.yml`
  or similar) mounted from a Kubernetes Secret.
- The `Config` dataclass and `load_config()` are replaced by a thin
  validated wrapper over `settings.*` keys, or removed in favour of direct
  `settings` attribute access.
- Helm test pods consume the same profile files as the service pods,
  eliminating the separate `config-{component}-secret.yml` key that the
  storefront Secret currently emits for the test pod.

This is a prerequisite for clean secret injection (wallet keys, API keys)
via the standard Helm Secret + profile pattern.

---

## Registry Service — Planned Rework

### 1. Registry as shared marketplace infrastructure (not per-node)

**Status:** Planned.

**Problem:** The `registry-service` is currently deployed as a subchart of the `arkhai-node-operator` Helm chart, implying it is part of every provider node's deployment. In practice the registry is a shared marketplace service — there is one per market, not one per provider. Multiple seller nodes should all register with and publish orders to the same registry instance run by the marketplace operator. Bundling it with the provider chart conflates the marketplace operator role with the provider role.

**Planned fix:** Make `registry` an optional subchart (add `condition: registry.enabled`, default `false`). Provider deployments point at an externally-operated registry via `global.registry.api_url`. Only marketplace operator deployments enable the subchart. Document the two deployment topologies (operator vs. provider) in the Helm `values.yaml` and in this file.

---

### 2. Event sync full-history gap

**Status:** Planned.

**Problem:** `EventSyncService.sync_from_start()` only scans the last 1000 blocks for `Registered`, `MetadataSet`, and `URIUpdated` events. On a live chain with registrations months ago this window misses all historical agents. The registry's agent count is therefore a function of how recently agents registered, not how many are actually on-chain.

**Planned fix:** Replace the sliding window with a full enumeration using view functions: call `totalSupply()` on the IdentityRegistry to get the count of registered agents, then call `ownerOf(id)` and `tokenURI(id)` for each token ID from 0 to `totalSupply()-1`. This is a set of pure read calls with no event history dependency, works correctly on any RPC provider, and is immune to block range limits. The periodic sync can still use event filtering for incremental updates after the initial full enumeration.

---

## Provisioning Service — Planned Rework

The following items represent known architectural deficiencies in `provisioning-service` that are planned for remediation. They are documented here to provide context when working on this service.

> **TODO(client-compat): The provisioning-service package currently exposes its modules at the flat `client.*` level (e.g. `from client.provisioning_client import ...`) because setuptools maps `src/` directly as the package root. To expose a clean `provisioning_service.*` namespace, all internal imports within the package would need to be converted from bare names (e.g. `from models.jobs_model import ...`) to relative imports (e.g. `from .models.jobs_model import ...`). Until that refactor is done, `service/clients/provisioning.py` imports from `client.provisioning_client` rather than `provisioning_service.client.provisioning_client`.

> **TODO(smoke-tests):** The provisioning smoke tests in `integration-tests/tests/smoke/test_provisioning_smoke.py` use raw `httpx` calls rather than `SyncProvisioningClient`. They should be updated to use the canonical client following the pattern established in `registry-service/tests/integration/` and the storefront integration tests.

#### `escrow_uid` on jobs — deal linkage and recovery

The `ansible_jobs` table now carries an `escrow_uid` column (nullable, indexed). The storefront passes this when submitting a provisioning job for a settled deal. It enables the storefront to recover the provisioning job_id after a crash by querying `GET /api/v1/jobs?escrow_uid=<uid>` rather than losing the mapping.

`escrow_uid` is surfaced in:
- `AnsibleJobParams.escrow_uid` (internal DTO)
- `JobStatusResponse.escrow_uid` (HTTP response)
- `GET /api/v1/jobs?escrow_uid=<uid>` filter on the list endpoint
- `ProvisioningClient.list_jobs(escrow_uid=...)` on both async and sync clients

The `provisioning_job_id` is surfaced in `GET /settle/{escrow_uid}/status` on the storefront so the buyer can traverse: storefront settle status → `provisioning_job_id` → provisioning `GET /jobs/{id}`.

#### Test controller (`/test/*`)

Only mounted when `mock` is in `ACTIVE_PROFILES`. Never present in production or staging.

Provides an HTTP API for configuring `ProgrammableMockAnsibleService` rules and waiting for job lifecycle events without polling loops.

**Endpoints:**

```
POST   /test/mock-rules                    Add a when→then mock rule
GET    /test/mock-rules                    List active rules
DELETE /test/mock-rules/{rule_id}          Remove a rule
POST   /test/mock-rules/{rule_id}/resume   Release a paused job gate
GET    /test/jobs/summary                  Status counts (non-blocking)
GET    /test/jobs/drain                    Long-poll until all jobs terminal
GET    /test/jobs/{job_id}/wait            Long-poll until one job is terminal
```

**Mock rule schema:**
```json
{
  "rule_id": "my-ww1-create",
  "match": {"vm_action": "create", "vm_host": "ww1"},
  "pause_before_result": true,
  "result_stdout": "...",
  "fail_with": null
}
```

Rules are evaluated in insertion order. The first rule whose `match` dict is a subset of the incoming `AnsibleJobParams` fields wins. `match: {}` is a catch-all. If no rule matches, `_FAKE_STDOUT` success path runs.

`pause_before_result: true` makes `wait_for_playbook` block on an `asyncio.Event` until `POST /test/mock-rules/{rule_id}/resume` is called. This allows tests to assert on mid-flight job state without any `asyncio.sleep` polling.

**`ProgrammableMockAnsibleService`** is activated instead of `MockAnsibleService` when `mock` is in `ACTIVE_PROFILES`. It extends `MockAnsibleService` with the rule dict and per-rule `asyncio.Event` gates. Both are in `services/mock_ansible_service.py`.

**Rule matching seam:** `AnsibleJobService._process_job` injects the `AnsibleJobParams` onto the `AnsibleRun` handle as `run._params` immediately after `start_playbook`. `ProgrammableMockAnsibleService.wait_for_playbook` reads `getattr(run, "_params", None)` to match rules. The real `AnsibleRun` dataclass ignores unknown attributes; this is a zero-cost test seam.

**Job-done event seam:** After every job reaches a terminal state, `_process_job` calls `getattr(self._ansible, "notify_job_done", None)` — a no-op on the real `AnsibleService`. `ProgrammableMockAnsibleService.notify_job_done` fires a per-job `asyncio.Event` stored in `_job_done_events`, which `GET /test/jobs/{job_id}/wait` awaits. This replaces any `asyncio.sleep` polling in test code.

**Helm TODO:** Add `global.adminApiKey` to `values.yaml`; render into `config-provisioning-secrets.yml` so the e2e test pod can authenticate to the test controller (same key used for storefront admin endpoints).

#### 1. Golden image configuration (`management-vars.yaml`)

**Problem:** The `golden-image-build` Ansible role writes `management-vars.yaml` to the operator's local machine with root SSH credentials for the golden image. The provisioning service reads these credentials through the standard dynaconf profile system, but the key names in `management-vars.yaml` do not match the names in `settings.toml`.

**What the provisioning service needs from `management-vars.yaml`:**
- `golden_root_ssh_filename` → maps to `settings.golden_root_ssh_filename`
- `golden_root_ssh_password` → maps to `settings.golden_root_ssh_password`
- `golden_image_name` → maps to `settings.golden_image_name`
- `golden_gcs_bucket` and `golden_gcs_project` → in `settings.toml`

**Decision:** The Ansible role should write `management-vars.yaml` keys using the exact names that dynaconf expects (matching `settings.toml`). The operator then includes the relevant keys in the Helm `values.yaml` `config:` block. No separate loader class or file-format adapter is needed.

> **TODO(management-vars):** Update `golden-image-build.yml` in `compute-provisioning-iac` to write key names matching `settings.toml` (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`). Document the operator workflow for getting `management-vars.yaml` into the Kubernetes Secret in `compute-provisioning-iac/README.md`.

**`VmActionRequest` — shared optional body:**

Simple lifecycle actions (`start`, `shutdown`, `reboot`, `destroy`, `undefine`, `monitor`, `reset-password`, `cancel_expiry`) share one optional body model `VmActionRequest(buyer_agent_id, max_retries)`. The `build_simple_params(action, host, body, vm_name)` helper in `vm_request_model.py` produces `AnsibleJobParams` from path parameters + this body. `CreateVmRequest` and `ScheduleVmExpiryRequest` remain distinct classes with their own fields.

**`HostController.check_capacity` — future:** should eventually accept optional resource filter parameters (`vcpus`, `ram_mb`, `gpu_count`) and return ranked hosts with sufficient capacity — useful for the agent's pre-flight check before a `create` job.

### 2. Implement reliable lease expiry detection

**Problem:** The current lease mechanism schedules a Unix `at` daemon job on the KVM host at the moment `lease_end` is called. After that, the provisioning service has no further awareness of whether the lease timer fired, whether the cleanup script ran, or whether the VM was actually destroyed. There is no polling, no callback, no record in the provisioning database. If the `at` daemon is not running, if the KVM host reboots before the lease time, or if the agent never calls `lease_end` at all (e.g., due to a crash), the VM runs indefinitely.

**Planned fix:** Implement a lease expiry watchdog inside the provisioning service. Design options to evaluate:

- **Option A — DB-driven polling loop:** When a `lease_end` job succeeds, write the `vm_name`, `vm_host`, and `lease_end_utc` to a `vm_leases` table. A background task wakes periodically (e.g., every minute), queries for leases past their expiry time, and submits a destroy + cleanup job for each. This makes the provisioning service the authoritative lease timer rather than the KVM host's `at` daemon. The `at`-based scheduling in the Ansible playbook would be retired.
- **Option B — polling the `at` queue:** Submit a `check` job against the host periodically to verify that expected `at` jobs are still pending. This is fragile and doesn't solve the "agent never called lease_end" case.

Option A is the preferred direction. The `vm_leases` table should also be exposed via API so administrators can see what leases are active, when they expire, and what their current state is — without SSHing to the host.

---

## Testing Strategy

> **Test execution context:** The e2e / system integration test suite runs from a **Helm test pod** inside the cluster. It cannot import or instantiate service code in-process. All assertions are made over HTTP against live services using typed client libraries. This affects every layer of the test design: there is no `ASGITransport`, no monkeypatching of service internals, and no direct DB reads from the test pod. Visibility into service state is provided exclusively through HTTP endpoints — which is why the storefront and provisioning service expose rich read APIs rather than relying on direct DB inspection.

This section defines the testing conventions for the Arkhai Market Stack. It exists to give every contributor a consistent mental model of what each test level is responsible for, what it is explicitly not responsible for, and how the levels relate to each other. New tests should be placed at the lowest level that can meaningfully exercise the behaviour in question.

### Four-Level Hierarchy

#### 1. Unit Tests

**What they cover:** Classes in isolation. A unit test instantiates one class, passes in mocked collaborators for all injected dependencies, and asserts on the return value or side effects of a specific method.

**What they do not cover:** Orchestration — if a function's sole purpose is to call other functions in sequence, that function does not have meaningful unit tests. The correctness of the sequence is an integration test concern. Lower-level functions that are the final abstraction before an external boundary (a database write, a subprocess invocation) are similarly not meaningful to unit test in isolation; their behaviour is validated by integration tests against the real boundary or a well-defined mock of it.

**What to focus on in this codebase:**
- `AnsibleService`: `_build_vm_vars` (YAML serialisation of every field combination), `_extract_ssh_port` / `_extract_tenant_user` / `_extract_ansible_json` (output parsers against representative playbook output strings).
- `AnsibleJobService`: `_build_params` (dict → `AnsibleJobParams` mapping), `_redact_logs` (regex redaction), `_calculate_retry_delay` (backoff arithmetic), `_should_retry_error` (error string matching), `_build_result_payload` (structured result assembly from `AnsibleRunResult`).
- `models/vm_request_model.py`: `CreateVmRequest` Pydantic validation (FRP cross-field rule, field constraints), `ScheduleVmExpiryRequest` required field, `build_simple_params` action routing.
- `HostService`: `seed_from_ini` (INI parsing, upsert idempotency), `register_host` with `embedded` key (Fernet encryption round-trip), `render_inventory_ini` (correct `[kvm_hosts]` group + variable output), `list_hosts(enabled_only=True)` filter.

**Mocking convention:** Use `unittest.mock.MagicMock` / `AsyncMock` for injected collaborators. Do not patch module-level imports; instead, pass mocks in via the constructor (the DI design makes this natural).

#### 2. Integration Tests

**What they cover:** End-to-end HTTP request → response paths with the full application stack running (FastAPI app, real SQLite DB, DI container wired) and a controlled mock at the external I/O boundary. Orchestration logic, the job processing loop, retry behaviour, and error propagation are all validated here.

**What they do not cover:** Every edge case of data transformation logic — that belongs in unit tests. Integration tests need one representative case per external mock behaviour, not exhaustive parametrisation.

**External boundary definition:** Any I/O that crosses a process boundary. In this codebase that means:
- Ansible subprocess invocations — mocked at `AnsibleService` (replace `start_playbook` / `wait_for_playbook` / `check_connectivity`)
- The ERC-8004 registry HTTP call in `AgentAuthMiddleware` — bypassed by disabling auth (`enable_auth=false` in test settings)

**Test setup pattern:** Use `httpx.AsyncClient` with `ASGITransport` against the real `app` instance, injected via the canonical `FooClient(transport=...)` constructor. Override container providers for `AnsibleService` before the test and restore them after. See `src/tests/integration/conftest.py` for the full fixture implementation.

**Client contract verification:** Integration tests call `ProvisioningClient` methods directly against the in-process app. Route strings, request body shapes, and response parsing are owned by the client — no raw HTTP calls appear in test code. If the API renames a field or changes a route, the client method raises `ProvisioningError` and the test fails immediately.

**State setup convention:** Test precondition state (e.g., a job row that must already exist before the endpoint under test is called) should be created through the HTTP API where feasible. Use direct DB factory functions only for state that is not expressible through any API endpoint — this keeps integration tests honest about the API contract.

**Async test discipline — no sleeps:** Tests that exercise the background job processing loop must never use `asyncio.sleep` or `await asyncio.wait_for(..., timeout=...)` to wait for side effects. These approaches always produce intermittent failures. The correct pattern uses the `on_job_started` seam on `AsyncJobQueue`:

```python
job_dispatched = asyncio.Event()

def _on_started(job_id: str) -> None:
    job_dispatched.set()

job_queue._on_job_started = _on_started

response = await client.post("/api/v1/hosts/ww1/vms/", json={...})
await asyncio.wait_for(job_dispatched.wait(), timeout=5.0)
# Now safe to poll GET /api/v1/jobs/{job_id} for terminal state
```

`AsyncJobQueue.__init__` accepts `on_job_started: Optional[Callable[[str], None]]` as a test seam. It is `None` in production and zero-cost.

#### 3. Smoke Tests (Deployment Validation)

**What they cover:** Stateless, idempotent verification that a deployed stack is wired correctly — services can reach each other, authentication headers are enforced, health endpoints return 200, expected routes exist. These run as Helm test hooks in Kubernetes.

**What they do not cover:** Service semantics. By the time a smoke test runs, the semantics have already been validated by integration tests. A smoke test for the provisioning service should verify that `GET /health` returns 200 and that `POST /api/v1/hosts/ww1/vms/` returns 401 without an `X-Agent-ID` header — it should not submit a real provisioning job and poll for completion.

**Current location:** `helm/templates/tests/` as Kubernetes Job resources executed by `helm test`.

#### 4. System Integration Tests (End-to-End)

**What they cover:** Cross-service contracts — scenarios that require two or more services to interact over the network to produce a meaningful result. Examples: a buyer agent successfully negotiating with a seller agent and reaching a settled on-chain state; a provisioning job triggered by an agent completing and the buyer receiving credentials.

**What they do not cover:** Anything already covered by the three levels above. System integration tests are expensive to run and brittle to maintain; they should be minimal in count and cover only the cross-service contract, not any service's internal logic.

**Current location:** `integration-tests/tests/e2e/` — the `roles/` subtree organises tests by deployment layer (external chain, market registry, seller node) and negotiation stage (discovery, negotiation, settlement). This is planned to move to a separate project as the stack matures.

#### Full-Deal E2E Test (`tests/e2e/roles/scenarios/test_full_deal.py`)

The primary e2e test suite. 18 sequential tests covering the complete buyer-seller deal lifecycle. Tests run in numbered order; later tests skip automatically via `require_state(deal_state, "field_name")` if a prerequisite field was not populated, so the first failure is always the actionable one.

**Stage map:**

| Test | Stage | Observable |
|---|---|---|
| 00a | Policy seed | `POST /admin/policy/seed` — callable_count > 0, order_create policy seeded |
| 00b | Policy dry-run | `POST /api/v1/system/policy/evaluate` — action=make_offer |
| 01 | Create paused listing | `POST /orders/create` `{paused:true}` → `listing_id`, local only |
| 02 | Listing locally visible | `GET /api/v1/listings/{id}` → status=open, paused=True |
| 03 | Registry absent | `GET registry/orders?status=open` — listing NOT present |
| 04 | Resume publishes | `POST /api/v1/listings/{id}/resume` → registry_status=published |
| 05 | Registry present | `GET registry/orders?status=open` — listing NOW present |
| 06 | Admin pause blocks | `POST /negotiate/new` returns 503 |
| 07 | Admin resume allows | `GET /api/v1/system/status` → paused=false |
| 08 | Negotiation starts | `POST /negotiate/new` → negotiation_id (EIP-191 signed by buyer) |
| 09 | Negotiation visible | `GET /api/v1/listings/{id}/negotiations` lists thread |
| 10 | Force-accept converges | `POST .../force-accept` → action=accept, price=agreed |
| 11 | Terminal success | `GET .../negotiations/{neg_id}` → terminal_state=success |
| 12 | Mock escrow | deterministic `escrow_uid` captured (no real chain call) |
| 13 | Settlement submitted | `POST /settle/{uid}` → status=provisioning |
| 14 | Provisioning job | `provisioning_job_id` in settle status; job in provisioning API |
| 15 | Provisioning completes | `GET /test/jobs/{id}/wait` → succeeded (long-poll) |
| 16 | Settlement ready | `GET /settle/{uid}/status` → status=ready |
| 17 | Tenant credentials | `tenant_credentials` non-empty in settlement response |
| 18 | Seller listing accepted | `GET /api/v1/listings/{id}` → status=accepted or closed |

**`DealState`** — module-scoped dataclass accumulating IDs and snapshots. Key fields: `seller_listing_id`, `negotiation_id`, `agreed_price`, `escrow_uid`, `provisioning_job_id`, `settlement_status`, `tenant_credentials`. Also `_policies_seeded` and `_policy_evaluated` (bool) for the 00a/00b prerequisites.

**`/negotiate/new` signing:** `SyncStorefrontClient` has no `negotiate_new` method. The e2e test calls it via `storefront_client._client.post("/negotiate/new", ...)` with a manually constructed EIP-191 signature using `_sign_eip191(buyer_private_key, f"negotiate_new:{listing_id}:{ts}")` from `storefront_client.client`.

**Provisioning gate pattern:** Before submitting settlement (stage 13), add a `pause_before_result=True` mock rule via `ProvisioningTestClient.add_mock_rule`. Stage 15 calls `resume_rule` then `wait_for_job` (long-poll, no sleep). Note: the current test skips the gate setup — it's a known gap to wire in stage 12/15 properly.

**Topology requirements:**
- Storefront with `admin_api_key` set; `settings.SELLER.ADMIN_API_KEY` and `settings.SELLER.PRIVATE_KEY`
- Registry reachable; `settings.REGISTRY.API_URL`
- Provisioning with `ACTIVE_PROFILES=mock`; `settings.PROVISIONING.API_URL`
- Buyer wallet: `settings.BUYER.PRIVATE_KEY`, `settings.BUYER.WALLET_ADDRESS`
- `settings.SELLER.WALLET_ADDRESS` (for EIP-191 signing of `POST /orders/create`)

**`ProvisioningTestClient`** (`integration-tests/src/provisioning_test_client.py`) — sync HTTP client for the `/test/*` endpoints. Not part of `SyncProvisioningClient`; test infra only. Methods: `add_mock_rule`, `list_mock_rules`, `delete_mock_rule`, `resume_rule`, `job_summary`, `wait_for_job` (long-poll), `drain` (long-poll).

### Coverage Contract Between Levels

Each level has a defined jurisdiction. Duplicating coverage across levels creates maintenance burden without safety benefit:

| Concern | Unit | Integration | Smoke | System |
|---|---|---|---|---|
| Data transformation / parsing logic | ✅ exhaustive | one happy path | ❌ | ❌ |
| Pydantic validation rules | ✅ exhaustive | ❌ | ❌ | ❌ |
| Orchestration / job lifecycle | ❌ | ✅ exhaustive | ❌ | ❌ |
| Retry / backoff arithmetic | ✅ | one case | ❌ | ❌ |
| Auth middleware enforcement | ❌ | ✅ | one case | ❌ |
| Client ↔ API contract | ❌ | ✅ | ❌ | ❌ |
| Service-to-service wiring | ❌ | ❌ | ✅ | ❌ |
| Cross-service negotiation flow | ❌ | ❌ | ❌ | ✅ |

### Test File Layout

**provisioning-service** (reference layout):
```
provisioning-service/src/tests/
├── unit/
│   ├── conftest.py              # mock_settings fixture
│   └── services/
└── integration/
    ├── conftest.py              # app fixture, container overrides, DB setup, fake_ansible
    └── test_{controller}.py
```

**registry-service**:
```
registry-service/tests/
├── conftest.py                  # db_session fixture (in-memory SQLite), sign_order_auth helper
├── unit/
│   ├── test_agent_id_lookup.py  # find_agent_by_id — canonical ID parsing, case folding
│   ├── test_event_sync.py       # EventSyncService — chain event processing, error handling
│   ├── test_order_auth_utils.py # EIP-191 signature verification helpers (exhaustive)
│   ├── test_resource_filters.py # matches_resource_filters — compute/token/region/GPU/SLA
│   └── test_symmetric_orders.py # find_symmetric_order — bidirectional order matching
└── integration/
    ├── conftest.py              # RegistryClient wired to in-process app via httpx WSGITransport;
    │                            # shared agent/order fixtures; Hardhat key constants
    ├── test_agents.py           # GET /agents, GET /agents/{id}, GET /agents/search,
    │                            # POST /agents/register, POST /agents/{id}/heartbeat
    ├── test_listings.py           # GET /listings, GET /listings/{id}, POST /agents/{id}/listings,
    │                            # GET /agents/{id}/listings, DELETE /listings/{id}, full lifecycle
    └── test_system.py           # GET /health (including 503 on DB failure),
                                 # GET /api/v1/system/config, /sync, /stats
```

**Client contract enforcement in registry-service integration tests:**

All integration tests import `RegistryClient` from the `arkhai-registry-client` wheel and
exercise the API exclusively through it.  The transport is `httpx.WSGITransport(app=app)` —
real HTTP through the full FastAPI stack, no network socket.  If the API renames a field or
changes a response shape, the client's `from_dict` parser will either raise or silently drop
the field, and the assertion will fail immediately.  The `get_db` dependency is overridden
per-test to yield the fixture's isolated in-memory SQLite session.

Routes not yet surfaced on `RegistryClient` (PUT /listings/{id}, POST /agents/register details)
are exercised via `registry_client._http` — the raw httpx client — which still traverses the
full stack.  These are marked as candidates for client extension in follow-on work.

**integration-tests**:
```
integration-tests/
├── conftest.py                  # CLI options (--profile, --config-dir); sets env vars pre-import
├── src/                         # Shared clients and settings (not test files)
│   ├── agent_client.py          # SyncStorefrontClient adapter shim (see Re-export shims)
│   ├── registry_client.py       # SyncRegistryClient re-export shim
│   ├── settings.py              # dynaconf settings loader
│   └── web3_client.py           # Web3 connection helper
└── tests/
    ├── conftest.py              # Session fixtures: w3, rpc_settings, registry_settings,
    │                            # buyer_settings, seller_settings, min_eth_balance
    ├── helpers/                 # Shared helpers used by both smoke and e2e tests
    │   ├── addresses.py
    │   ├── polling.py
    │   ├── registry_helpers.py
    │   └── sqlite_reader.py
    ├── fixtures/                # Shared pytest fixtures (ABIs, etc.)
    ├── smoke/                   # Smoke tests — stateless deployment validation
    │   ├── test_contracts_smoke.py     # On-chain contract bytecode + owner()
    │   ├── test_registry_smoke.py      # Registry reachability, health, seeding
    │   ├── test_wallets_smoke.py       # Wallet balance + key/address consistency
    │   ├── test_provisioning_smoke.py  # Provisioning API health, host registry, auth
    │   └── test_storefront_smoke.py    # Seller storefront reachability + registration
    └── e2e/                     # System integration tests — cross-service scenarios
        └── roles/               # Organised by deployment layer and negotiation stage
            ├── conftest.py      # Imports layer fixtures (external_world, market_registry, seller_node)
            ├── helpers/         # deal.py (full deal flow helper), erc20.py
            ├── layers/          # test_external.py, test_market.py, test_seller.py
            └── stages/
                └── discovery/test_buyer.py
```


### Problem
Python packages in this monorepo need to consume each other (e.g. the storefront imports the provisioning service client). Relative path imports across project directories are fragile — they encode layout assumptions and break when projects move. Native extension wheels (those with platform/ABI tags like `cp312-cp312-linux_x86_64`) must be compiled inside the target Docker environment; this is why `alkahest-py` ships pre-built wheels for each platform in `storefront/packages/`. Pure Python wheels (`py3-none-any`) have no such constraint and can be built safely on the host.

### Current Approach: `--find-links` flat wheel directory

Pure Python internal packages are built as wheels and placed in `.dist/` at the monorepo root before Docker images are built. Docker images consume them via `uv sync --find-links /dist`.

**Build sequence:**

```
make dist          →  uv build for each pure-Python package  →  .dist/*.whl
make build         →  docker build (COPY .dist/ /dist/, uv sync --find-links /dist)
```

`make dist` runs automatically as a prerequisite of `make build-runtime-images`.

**Directory structure:**

```
simple-market-service/   ← monorepo root
  .dist/                 ← gitignored; populated by make dist
  buyer/
  storefront/
  policy/
  infra/
  service/
  registry-client/
  storefront-client/
  registry-service/
  provisioning-service/
  ...
```

TODO: Add notes on contents of these folders.

**Guard:** `make dist-provisioning` asserts the output wheel filename ends in `-none-any.whl`. If a C extension or Rust crate is ever added to a package, the build fails loudly with an error directing the developer to move compilation inside the Docker build context.

**Why `--find-links` is passed on the CLI, not in `pyproject.toml`:**

`find-links` encodes a filesystem path. The path differs between environments:

- **Docker:** `.dist/` is copied to `/dist/` inside the image; `uv sync --find-links /dist` is passed in the `RUN` instruction.
- **Local dev:** `.dist/` lives at the monorepo root; `uv sync` and `uv run` must be invoked with `--find-links ../.dist` (set in each sub-project's Makefile targets). Note: `UV_FIND_LINKS` is **not** equivalent — it is not read by `uv sync` or `uv lock`; only the `--find-links` CLI flag works for dependency resolution.

Setting `find-links` in `pyproject.toml` bakes one of these paths into the lockfile and breaks the other context. Setting it via `UV_FIND_LINKS` on the command line means the path stays out of version-controlled files entirely.

**Rule:** `pyproject.toml` and `uv.lock` files must never contain `find-links` entries or `[tool.uv.sources]` path references for `market-service`, `provisioning-service`, `arkhai-storefront-client`, or `arkhai-registry-client`. These packages are resolved exclusively from wheels in `.dist/`.

**Why not `uv.sources` editable installs:** Editable path references (`{ path = "../service", editable = true }`) are resolved relative to the project root at lockfile generation time, then embedded in `uv.lock`. Inside Docker the relative path no longer exists, causing resolution failures. The wheel approach avoids this by making both the path and the mechanism context-specific (CLI flag, not lockfile entry).

### Internal wheel packages

Three pure-Python internal packages are distributed as wheels:

| Package | Wheel name | Source | Primary consumers |
|---------|-----------|--------|-------------------|
| `market-service` | `market_service-*.whl` | `service/` | `core`, `integration-tests` |
| `provisioning-service` | `provisioning_service-*.whl` | `provisioning-service/` | `integration-tests`, `service` |
| `arkhai-storefront-client` | `arkhai_storefront_client-*.whl` | `storefront-client/` | `storefront`, `integration-tests` |
| `arkhai-registry-client` | `arkhai_registry_client-*.whl` | `registry-client/` | `integration-tests` |

`arkhai-storefront-client` exists as a separate lightweight package to avoid pulling `market-storefront`'s heavyweight dependencies (`pufferlib`, `torch`, native RL wheels under the `[rl]` extra) into projects that only need the HTTP client and EIP-191 signing helper. The canonical implementation lives in `storefront-client/src/storefront_client/client.py` and exposes `StorefrontClient` (async) and `SyncStorefrontClient` (sync).

**`arkhai-storefront-client` versioning policy:**

`arkhai-storefront-client` encodes two contracts with the agent server (`storefront/src/market_storefront/agent.py`) that are not enforced at import time — mismatches produce silent 403s or wrong response shapes at runtime:

1. **Auth message format** — `_build_auth_headers` must match `_check_agent_request_auth` in `agent.py`:
   - `create_order` → `"create_order:<agent_wallet_address>:<timestamp>"`
   - `close_listing` → `"close_order:<listing_id>:<timestamp>"`

2. **Endpoint signatures** — `/listings/create`, `/listings/close`, `/alerts/resource` request/response shapes.

When either contract changes: bump `version` in `storefront-client/pyproject.toml`, update the minimum version constraint in all consuming `pyproject.toml` files, rebuild the wheel with `make dist-storefront-client`, and run `make init` in each consumer. Keep all changes in one commit so the version boundary is auditable in git history. See `storefront-client/README.md` for the full checklist.

### Upgrade path

**Near term — PEP 503 local index:** Run `scripts/gen_simple_index.py .dist/` after `make dist` to generate `index.html` files. Switch from `--find-links .dist` to `--index file://${PWD}/.dist`. The script is 50 lines of stdlib Python and requires no maintenance per package added.

**Long term — GCP Artifact Registry:** The project already uses GAR for `alkahest-py`. When ready: `uv publish --index https://...gar.../simple .dist/*.whl`. Consumer-side change is one URL in `pyproject.toml`. No structural changes elsewhere.

### Canonical client design pattern

Every service that has HTTP consumers provides two client classes with identical method signatures:

```
FooClient          — async, backed by httpx.AsyncClient
SyncFooClient      — sync,  backed by httpx.Client
```

Both classes:
- **Own their HTTP session internally** — callers never create or pass a session object
- **Accept a `transport=` kwarg at construction** for in-process test injection
- **Raise a typed `FooClientError`** (subclass of `Exception`) on non-2xx responses
- **Return typed model objects** from all methods — no raw dicts exposed

```python
# Production (real network)
client = SyncRegistryClient("http://registry:8080")
agents = client.list_agents(limit=10)

# In-process integration test (no network socket)
client = RegistryClient("http://test", transport=httpx.ASGITransport(app=app))
agents = await client.list_agents(limit=10)
```

**Why httpx, not aiohttp:** `httpx` provides both `AsyncClient` and `Client` with identical interfaces, and crucially supports `ASGITransport` for driving ASGI apps (FastAPI) in-process without a network socket. `aiohttp` has no ASGI transport and requires a `ClientSession` to be passed per-call, which leaks transport concerns into callers.

**No session argument:** Methods do not accept a session. The client owns its session lifecycle. Use the client as a context manager or call `close()` explicitly:

```python
async with RegistryClient("http://registry:8080") as client:
    health = await client.get_health()

# or
client = SyncRegistryClient("http://registry:8080")
try:
    health = client.get_health()
finally:
    client.close()
```

**No module-level wrapper functions:** Functions like `provision_machine_async()` or `schedule_vm_expiry_async()` that wrap client methods are removed. Callers instantiate the client and call methods directly.

**Transport injection for integration tests:** Service integration tests use `FooClient` (async) with `httpx.ASGITransport(app=app)`. The fixture wires `get_db` override and yields the client — tests call methods, never route strings:

```python
@pytest_asyncio.fixture
async def registry_client(db_session):
    app.dependency_overrides[get_db] = lambda: ...
    async with RegistryClient("http://test", transport=httpx.ASGITransport(app=app)) as client:
        yield client
    app.dependency_overrides.clear()

async def test_list_orders(registry_client):
    result = await registry_client.list_orders()   # no route strings
    assert result.orders == []
```

**`SyncFooClient` for smoke tests:** Smoke tests run against real deployed endpoints over a real network socket. They use `SyncFooClient` directly — no shims, no `asyncio.run()`:

```python
client = SyncRegistryClient(base_url=registry_api_url)
health = client.get_health()
```

**Iteration workflow for wheel consumers:** When iterating on a client package during development, use `make reinit` (not `make init`) to force reinstallation without bumping the version:

```
make dist-registry          # rebuild wheel
cd registry-service && make reinit && make test-integration
```

`reinit` runs `uv sync --reinstall-package <pkg>` which pulls fresh from `.dist/` regardless of cache.

### Client package inventory

| Package | Wheel | Async client | Sync client | Consumers |
|---|---|---|---|---|
| `storefront-client/` | `arkhai_storefront_client-*.whl` | `StorefrontClient` | `SyncStorefrontClient` | `storefront`, `integration-tests` |
| `registry-client/` | `arkhai_registry_client-*.whl` | `RegistryClient` | `SyncRegistryClient` | `integration-tests`, `registry-service` tests |
| `provisioning-service/src/client/` | `provisioning_service-*.whl` | `ProvisioningClient` | `SyncProvisioningClient` | `storefront`, `integration-tests`, `service` shim |

`arkhai-storefront-client` is a separate lightweight package (not bundled with `storefront`) to avoid pulling heavyweight dependencies (`pufferlib`, `torch`, native RL wheels) into consumers that only need the HTTP client and EIP-191 signing.

`provisioning-service` bundles its client inside the service wheel (under `src/client/`) because the request/response models (`CreateVmRequest`, `JobStatusResponse`, etc.) are shared between the server and client. Consumers import as `from client.provisioning_client import ProvisioningClient`.

### Re-export shims

**`integration-tests/src/agent_client.py`:** a compatibility adapter wrapping `SyncStorefrontClient` from the wheel. Preserves the `AgentClient` interface expected by the smoke tests (constructor-level `agent_wallet_address`, `get_registration_file()`, single-arg `create_order()`). The docstring in that file lists the steps to remove it once the smoke tests are updated to call `SyncStorefrontClient` directly.

**`integration-tests/src/registry_client.py`:** re-exports `SyncRegistryClient as RegistryClient` from the canonical wheel. Preserved for the smoke test import path `from src.registry_client import RegistryClient`. A future task can update the smoke test imports and delete this file.

| Term | Meaning |
|---|---|
| Alkahest | Arkhai's smart contract suite for peer-to-peer agreements and escrow |
| ERC-8004 | Ethereum standard for on-chain agent identity (ERC-721-based) |
| Storefront | The seller-side HTTP server (`market-storefront serve`); the only running agent process in the negotiation flow |
| Canonical agent ID | `eip155:{chainId}:{registryAddress}:{tokenId}` |
| FRP | Fast Reverse Proxy — used to give buyers network access to their VMs |
| Anvil | Local EVM testnet node from Foundry |
| EIP-191 | Personal-message signature scheme used to authenticate buyer→seller HTTP request bodies |
| Policy callable | A registered function that evaluates a negotiation event and may return an action |
| Order | A published offer in the registry; has `offer_resource`, `demand_resource`, status |