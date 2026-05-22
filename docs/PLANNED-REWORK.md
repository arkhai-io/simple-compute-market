# Planned Rework

Pending architectural work for the Arkhai market stack. Cross-references `ARCHITECTURE.md` for current-state context.

---

## Core Stack

### Chain-Agnostic Contract Deployment

**Status:** Planned. CLI surface exists; the underlying deployer scripts still ignore it.

**Problem:** The `market-infra chain deploy-contracts` CLI accepts `--rpc-url`, `--deployer-key`, and per-suite flags (`--erc8004/--alkahest/--eas`) and exports `RPC_URL` / `ANVIL_RPC_URL` into the deployer subprocess environment. But `market-contract-deployer/deploy_alkahest.py:22` still has `RPC_URL = "http://anvil:8545"` as a module-level constant, line 27 uses Anvil account #0 (`0xf39Fd6…`) as the deployer, and `deploy-local.sh:12-14` hardcodes the ERC-8004 CREATE2 vanity addresses (`0x8004A8…`, `0x8004B6…`, `0x8004Cb…`) that are deterministic only on chain id 31337. The script does not read the env vars the CLI plumbs through, so passing `--rpc-url` to `market-infra` has no effect on the actual deployment.

**Planned fix:**
- Make `deploy_alkahest.py` actually read `RPC_URL` / `ANVIL_RPC_URL` and a deployer key from env (with sensible Anvil defaults preserved for the local-dev path).
- Drop the CREATE2 vanity-address requirement in `deploy-local.sh`, or accept per-chain addresses passed in via flag/env so ERC-8004 contracts deploy at whatever address the deployer key gets.
- The `--no-eas --alkahest` separation in `market-infra chain deploy-contracts` is upstream-blocked: the alkahest deploy fixture currently always bundles EAS. Until alkahest accepts an externally-deployed EAS address, the flags are coupled and the CLI warns when toggled apart.

This closes the bootstrapping path for a market operator standing up the stack against a real chain — the wiring is mostly in place, only `deploy_alkahest.py` and `deploy-local.sh` need to honour what the CLI already exposes.

---

### Native Launch CLI for Provisioning Service

**Status:** Planned. Registry has a wrapper (`market-infra registry start` → `make serve`); provisioning doesn't.

**Problem:** The provisioning service is launched today only via raw `uvicorn` in its Dockerfile (`provisioning-service/Dockerfile:105`). There is no native, `pip install …` + run path — running it without docker-compose requires manually invoking uvicorn against the right module and managing the worker process separately. This blocks the "provider runs a provisioning service" half of the four-parties topology: a provider should be able to install and run the service on their own machine without inheriting the dev stack's container assumptions.

**Planned fix:** add a `provisioning-service` console script that wraps both the API uvicorn process and the worker process (likely as two subcommands: `provisioning-service serve` and `provisioning-service worker`). Compose / Helm configs then invoke the console script instead of `uvicorn …` directly. Mirrors how `registry-service` is now reachable via `market-infra registry start`.

The `provisioning-service` wheel stays its own distributable — it's operated by providers, who already install `market-storefront` from a separate wheel, and the existing Helm chart structure already treats it as a separate workload.

---

### Storefront DB Pruning

**Status:** Planned. Needs dormant-code verification before any DROP.

**Problem:** The seller-side storefront DB still carries tables that were introduced for the event-driven dispatcher model and may no longer be exercised after the buyer rewrite and the settlement decoupling from `ACCEPT_OFFER`. Candidates in `storefront/.../sqlite_client.py`:

- `decisions` (line 254) and `resource_transition_events` (line 621) — both started life as audit logs; if nothing reads them in production paths they belong in structured logs, not SQLite.
- `policies` (line 229) and `policy_composites` (line 241) — only needed if policies are user-configurable at runtime. If policy is just code (the file-policy discovery flow now in `sync_negotiation._discover_file_policies`), these tables disappear.
- `negotiation_messages` (line 427) — held the per-round message log so a daemon could resume mid-negotiation across restarts. Now that `/negotiate/{new,continue}` is synchronous HTTP and the buyer holds the run-log JSONL, the message log may be dead.

**Planned fix:** for each table, grep for readers (not just writers) outside of test code. If a table is only ever written and never read on a production path, delete the table and its writes. Verify the file-policy discovery flow fully replaces `policies` / `policy_composites` before dropping them. `negotiation_threads` itself stays — it's still the seller's record of an in-flight negotiation.

The `orders → listings` rename is already done; the plan's older framing of "drop the orders mirror" is obsolete (`listings` is the seller's primary entity now, not a registry mirror).

---

### "Agent" → "Storefront" Internal Naming Mop-Up

**Status:** Planned. The user-facing rename (CLI flags, wire JSON keys, table names, doc surfaces) is done; internal terminology has residue.

**Context:** "agent" in this codebase has two meanings — the ERC-8004 protocol concept (`agent_card`, `agent_id` as on-chain numeric ID, `IdentityRegistry`, `AgentRegistered`, `register_onchain`, `agent_heartbeat`) and historical references to the seller's runtime process from the ADK era. The first set is protocol-defined and stays. The second set should be `storefront`. The user-facing pass (`market-storefront provide` → `publish`, `--agent-url` CLI flag → `--storefront-url`, `agent_settings` test fixtures) is done; the remaining items are internal:

- **`storefront/src/market_storefront/agent.py`** — residual startup-helpers module (docstring: "Storefront startup/background-task helpers"). A sibling `server.py` already exists; this file should be folded into `server.py` or renamed to something purpose-named (e.g. `startup.py`). Importers: `server.py` (lifespan), `identity_controller.py`.
- **`AGENT_DB_PATH` env var** — referenced in `README.md:81`, `ARCHITECTURE.md`, `storefront/scripts/import_resources_csv.py:41,81,82`, `buyer/config/agent.schema.yaml:45`. Rename to `STOREFRONT_DB_PATH`. The dynaconf-prefix convention is `STOREFRONT_*` (`storefront/.../utils/config.py`), so this lines up cleanly.
- **One stray `agent_db_path` setting** in `integration-tests/tests/e2e/roles/layers/test_seller.py:61,82` via `AGENTS.SELLER_DB` — rename when touching the surrounding config.

**Not worth chasing:** the internal `agent_url` parameter name in `cli_publish.py`, `groups/escrow.py`, `action_executor.py`, `sync_negotiation.py`, `negotiation_models.py` (`buyer_agent_url`), etc. It's pervasive, internal-only (no wire surface), and the value plumbed through is consistently a storefront URL. Rename opportunistically; don't sweep.

---

### Registry Filter-Spec `indexed: true` Side Indexes

**Status:** Deferred until query latency on `/listings` demands it.

**Problem:** The registry's filter-spec YAML supports an `indexed: bool` annotation per filter (`registry-service/src/api/filter_spec.py:58` — `indexed: bool = False  # reserved for (a2); registry ignores today`). The intent was that hot filter axes (`token`, `gpu_model`) could opt into a registry-side denormalized index — generated column + index for scalar paths, side table for array-projection paths — populated at publish/update time. Today every filter evaluates in-memory via `jsonpath-ng` over the full row set; no side indexes exist, and no filter in `registry-service/filter-spec.yaml` declares `indexed: true`.

**Planned fix:** when query latency on `/listings` starts mattering, wire the `indexed: true` path:
- For scalar JSONPath filters (e.g. `$.offer_resource.gpu_model`): generated column + B-tree index, maintained by the publish/update writer.
- For array-projection filters (e.g. `$.accepted_escrows[*].fields.token`): a side table keyed on `(listing_id, value)`, repopulated on publish/update.
- The evaluator narrows on indexed scalar filters first, then evaluates non-indexed and array-projection filters on the survivor set.

Until then: the `indexed: bool` field stays as a no-op in the loader so the YAML stays forward-compatible. Current row counts make this a non-issue.

---

### Shared Dynaconf Bootstrap

**Status:** Planned. Two copies in the tree today.

**Problem:** `provisioning-service/src/config.py` (~100 LOC) and `integration-tests/src/settings.py` (~80 LOC) each carry their own near-identical Dynaconf bootstrap (profile selection from `ACTIVE_PROFILES`, `CONFIG_DIRECTORY` resolution, deep-merged `settings.toml` → `.secrets.toml` → `config.yml` → `config-<profile>.yml` → env vars layering). The storefront has since gained its own dynaconf loader at `storefront/src/market_storefront/utils/config.py` with the `STOREFRONT_*` prefix — that one is structurally similar but profile-free, so isn't part of the duplication.

**Planned fix:** lift the shared bootstrap (profile resolution + layered loader factory) into `service/` (the `market-service` wheel), where `config_loader.py` already lives. `provisioning-service` and `integration-tests` import from there and pass in their per-service prefix (`PROVISIONING_*` / `ARKHAI_*`) + defaults path. No behavior change; pure dedup.

---

### Storefront Admin CLI Test Coverage

**Status:** Planned. Test file was on the original split-plan TODO and never landed.

**Problem:** When the provider subcommands moved from the buyer CLI to `market_storefront.cli` (commit `a48ffb1`), the provider-side `register`/`serve`/`publish`/`portfolio` command tests were dropped from `buyer/tests/` and not re-added on the storefront side. `storefront/tests/unit/test_cli_publish_helpers.py` and `test_cli_serve.py` cover slices, but there's no umbrella `test_cli_admin.py` exercising the full subcommand surface.

**Planned fix:** add `storefront/tests/unit/test_cli_admin.py` covering each `market_storefront.cli` subcommand: argument parsing, config-file resolution, the `register` → `serve` → `publish` happy path against a mocked storefront, and the error cases for missing wallet / missing config / unreachable chain.

---

## Latent Bug Fixes

These were extracted from `ARCHITECTURE.md` "Known Issues & Areas of Concern" — they are genuine pending fixes rather than operational gotchas the current code lives with.

### SQLite INTEGER overflow for token amounts with `decimals > 0`

`negotiation_messages` stores `our_price`, `their_price`, and `proposed_price` as `INTEGER` columns (signed 64-bit, max `2**63 - 1 ≈ 9.2 × 10**18`). `accepted_escrows[i].price_per_hour` is stored in uint256-domain (already decimal-scaled at advertisement), and the negotiation pipeline carries those values into `our_price` / `their_price` unchanged. Any token with 18 decimals and a human-readable per-hour price above ~9.2 billion will overflow at the SQLite write.

**Workaround in e2e tests:** use `decimals: 0` on the MOCK test token so the advertised `price_per_hour` is already in base units.

**Fix:** change `our_price`, `their_price`, `proposed_price` in `negotiation_messages` from `INTEGER` to `TEXT` and parse at read time. The `accepted_escrows` JSON column already serializes `price_per_hour` as a string-of-digits to dodge this on the listing side; the price-tracking columns need the same treatment.

---

### `perform_registration` logs "Invalid explicit agent ID" when `ownerOf()` returns a tuple

On the local Anvil state, `identityRegistry.ownerOf(agent_id).call()` returns a 2-tuple instead of a plain address string (ABI mismatch). The `except Exception` block in `registration.py` catches this, sets `agent_id = None`, and falls through to blockchain event search which recovers correctly. The `[REGISTRATION] Invalid explicit agent ID N: (addr, addr)` log line is expected and non-fatal.

**Fix:** handle tuple returns explicitly in `registration.py` by unpacking `owner = result[0] if isinstance(result, (list, tuple)) else result`.

---

## Registry Service

### Shared marketplace infrastructure (not per-node)

**Status:** Planned.

**Problem:** The `registry-service` is currently deployed as a subchart of the `arkhai-node-operator` Helm chart, implying it is part of every provider node's deployment. In practice the registry is a shared marketplace service — there is one per market, not one per provider. Multiple seller nodes should all register with and publish orders to the same registry instance run by the marketplace operator. Bundling it with the provider chart conflates the marketplace operator role with the provider role.

**Planned fix:** Make `registry` an optional subchart (add `condition: registry.enabled`, default `false`). Provider deployments point at an externally-operated registry via `global.registry.api_url`. Only marketplace operator deployments enable the subchart. Document the two deployment topologies (operator vs. provider) in the Helm `values.yaml` and in `ARCHITECTURE.md`.

---

### Event sync full-history gap

**Status:** Planned.

**Problem:** `EventSyncService.sync_from_start()` only scans the last 1000
blocks for `Registered`, `MetadataSet`, and `URIUpdated` events. On a live
chain with registrations months ago this window misses all historical agents.
The registry's agent count is therefore a function of how recently agents
registered, not how many are actually on-chain. `REGISTRY_START_BLOCK` env
(read in `registry-service/src/config.py`) is the current escape hatch: a
fresh indexer can backfill from a known earlier block — typically the
IdentityRegistry's deployment block. This brings a new indexer up to date on
a known chain but leaves the 1000-block sliding window in place for
steady-state polling.

**Planned fix:** Replace the sliding window with a full enumeration using view
functions: call `totalSupply()` on the IdentityRegistry to get the count of
registered agents, then call `ownerOf(id)` and `tokenURI(id)` for each token
ID from 0 to `totalSupply()-1`. This is a set of pure read calls with no event
history dependency, works correctly on any RPC provider, and is immune to
block range limits. The periodic sync can still use event filtering for
incremental updates after the initial full enumeration.

---

## Provisioning Service

### Golden image configuration (`management-vars.yaml`)

**Problem:** The `golden-image-build` Ansible role writes `management-vars.yaml` to the operator's local machine with root SSH credentials for the golden image. The provisioning service reads these credentials through the standard dynaconf profile system, but the key names in `management-vars.yaml` do not match the names in `settings.toml`.

**What the provisioning service needs from `management-vars.yaml`:**
- `golden_root_ssh_filename` → maps to `settings.golden_root_ssh_filename`
- `golden_root_ssh_password` → maps to `settings.golden_root_ssh_password`
- `golden_image_name` → maps to `settings.golden_image_name`
- `golden_gcs_bucket` and `golden_gcs_project` → in `settings.toml`

**Decision:** The Ansible role should write `management-vars.yaml` keys using the exact names that dynaconf expects (matching `settings.toml`). The operator then includes the relevant keys in the Helm `values.yaml` `config:` block. No separate loader class or file-format adapter is needed.

**Planned fix:** Update `golden-image-build.yml` in `compute-provisioning-iac` to write key names matching `settings.toml` (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`). Document the operator workflow for getting `management-vars.yaml` into the Kubernetes Secret in `compute-provisioning-iac/README.md`.

---

### `HostController.check_capacity` resource filters

`HostController.check_capacity` should eventually accept optional resource filter parameters (`vcpus`, `ram_mb`, `gpu_count`) and return ranked hosts with sufficient capacity — useful for the storefront's pre-flight check before a `create` job.

---

### Lease expiry watchdog — check job result interpretation

See `ARCHITECTURE.md` "Lease Lifecycle — DB-driven watchdog" for current architecture.

**Remaining gap:** `LeaseLifecycleService._process_releasing_lease` polls the check job status but treats `succeeded` and `failed` uniformly (both proceed to patch the storefront). A future iteration should parse the check job result's `available_gpus` field: if `available_gpus > 0` the VM is confirmed gone and the patch proceeds normally; if `available_gpus == 0` the VM may still be running (late `at` daemon, cleanup race) and the watchdog should wait another cycle before forcing. This requires `AnsibleJobService._build_result_payload` to consistently expose `result.available.gpus` for the `check` action.

The `at`-based scheduling on the KVM host runs in parallel — the check job is a verification step, not a replacement for the `at` cleanup.

---

### Multi-Provider Resource Pool Architecture

This section documents architectural decisions reached for the provisioning service multi-provider refactor. Items are sequenced and cross-referenced with the `compute-market-internal-infra` ops repo `ARCHITECTURE.md` planned work section.

#### Background: Resource Pool Architecture

The provisioning service is being extended from a single-provider (Ansible/KVM)
system to a multi-provider, multi-pool system. The driver is GCP deployment: GPU
workloads on GCE cannot use nested VM provisioning (GPU passthrough from L1 GCE VM
to L2 nested VM is not a supported GCP configuration), so a GCP Compute API provider
is needed alongside the existing Ansible provider.

The design uses a `ComputeProvider` abstraction with per-lease pool selection via a
`PoolSelectorService` (label/tag matching analogous to Kubernetes node selectors). This allows a single provisioning service deployment to route leases to different providers and pool types based on the lease's resource requirements.

**Provider types planned:**
- `AnsibleProvider` — existing path, SSH into a KVM host and run `virt-install`.
  Requires pre-provisioned hosts in the `hosts` table.
- `GCPComputeProvider` — new, calls GCP Compute API directly. No pre-provisioned
  hosts required. Teardown via Compute API (independent of VM-internal state).

**Pool types:**
- `kvm_host` — Physical hosts in a data center or VMs acting as KVM hosts, Ansible provider
- `gce_vm` — GCE VMs as direct-access compute, GCP provider (GPU)

#### Data Model Changes

**New table: `resource_pools`**
```sql
CREATE TABLE resource_pools (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,  -- 'ansible' | 'gcp'
    pool_type       TEXT NOT NULL,  -- 'kvm_host | 'gce_vm'
	pool_config     TEXT FOREIGN KEY
    label           TEXT,
    policy_tags     JSON,           -- used by node selector service to choose a resource pool
);

CREATE TABLE gcp_pool_configs (
    id           TEXT PRIMARY KEY,
    project      TEXT,
    region       TEXT,
    zone         TEXT,
);
```

**Modified tables (migrations, backwards compatible):**
- `hosts`: add `pool_id TEXT REFERENCES resource_pools(id)`
- `vms`: add `pool_id TEXT REFERENCES resource_pools(id)` (nullable; set at VM
  creation time)
- `jobs`: add `provider_log_ref TEXT` (nullable; for GCP jobs, stores GCE operation
  ID for Cloud Logging cross-reference)
- `leases`: no changes

Initialization pattern for resource_pools and gcp_pool_configs should mirror host inventory seeding (populate on startup from file, admin enabled clobber endpoint for reconcilation). This will require an additional volume mount in the helm chart to support seeding from a file managed in the compute-market-internal-infra repo.

#### New Service Classes

**`ComputeProvider` (ABC)** — `create_vm`, `destroy_vm`, `get_capacity`,
`get_status`. All providers implement this interface.

**`AnsibleProvider(ComputeProvider)`** — extracts existing Ansible job runner logic.
Behavior identical to current implementation; this is a rename/extraction, not a
rewrite. Existing tests continue to pass.

**`GCPComputeProvider(ComputeProvider)`** — calls `google-cloud-compute` SDK.
`create_vm` uses Compute API create with data from lease and gcp_pool_config.
`destroy_vm` uses Compute API delete (no SSH required — critical security improvement).
Authenticates via Workload Identity Federation (WIF annotation on provisioning KSA).

**`ResourcePoolService`** — CRUD for resource pools; lookup by ID and tag filter.
JOIN with gcp_pool_config when provider is gcp

**`PoolSelectorService`** — pool selection given a lease request. v1: priority-ordered tag
matching. Designed to extend to scoring (cost, utilization) in a future item.

Design intended to mirror Kubernetes node selectors.

**`ProviderRegistry`** — maps `pool.provider` string to `ComputeProvider` instance.
Constructed in DI container at startup.

#### Modified Service Classes

**`LeaseService`** — calls `PoolSelectorService.select_pool(request)` before VM creation,
then dispatches to the selected pool's provider. All existing Ansible calls route
through `AnsibleProvider` unchanged.

**`LeaseWatchdog`** — looks up the lease's pool on expiry, dispatches to the pool's
provider for `destroy_vm`. Replaces hardcoded Ansible teardown dispatch.

**`mockMode` flag** — becomes a `MockProvider` registered in `ProviderRegistry` rather
than a service-level branch. Helm values flag preserved for backwards compatibility.

#### New Pool Controller

All gated by existing admin API key auth.

`POST /api/v1/pools` — create a resource pool. Body: pool table fields.

`GET /api/v1/pools` — list pools with tags and host counts.

#### GCP Provider e2e Test Scenario

A new e2e scenario (addition to `integration-tests/tests/e2e/`) validates the GCP
provider without mock provisioning:

1. `POST /api/v1/pools` — create a `gce_vm` pool.
2. `POST /system/lease-watchdog/pause` — hold expiry for inspection.
3. Full storefront → negotiate → settle → provisioning flow (reuse existing helpers).
4. Poll `GET /api/v1/jobs/{id}` until GCE VM is running (90-second timeout).
5. Verify SSH credentials returned; attempt SSH to GCE external IP.
6. `POST /system/lease-watchdog/resume` — trigger expiry.
7. Poll until lease `expired`; verify GCE instance deleted via Compute API.

This scenario validates the watchdog pause/resume admin endpoints, that GCPComputeProvider
creates real VMs, and that teardown is Compute-API-based (no SSH key required on the VM).
