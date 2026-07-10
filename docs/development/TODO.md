# Planned Rework

Pending architectural work and known operational issues for the Arkhai market stack. Cross-references `ARCHITECTURE.md` for current-state context.

---

## Index

| Item | Section | Status |
|------|---------|--------|
| [Init container migration & schema drift guard](#init-container-migration-pattern-and-schema-drift-guard) | State Management | Planned |
| [Registry: Postgres migration](#registry-postgres-migration) | State Management | Planned |
| [Market Core Extraction follow-ons](#market-core-extraction-follow-ons) | Core Stack | In progress |
| [Gradual typing for core packages](#gradual-typing-for-core-packages) | Core Stack | Planned |
| [Native Launch CLI for Provisioning Service](#native-launch-cli-for-provisioning-service) | Core Stack | Planned |
| [Storefront DB Pruning](#storefront-db-pruning) | Core Stack | Planned |
| [Registry Filter-Spec side indexes](#registry-filter-spec-indexed-true-side-indexes) | Core Stack | Deferred |
| [Shared Dynaconf Bootstrap](#shared-dynaconf-bootstrap) | Core Stack | Planned |
| [Move e2e Tests to Separate Project](#move-e2e-tests-to-a-separate-project) | Core Stack | Planned, no timeline |
| [Shared marketplace registry (not per-node)](#shared-marketplace-infrastructure-not-per-node) | Registry Service | Planned |
| [Golden image configuration](#golden-image-configuration-management-varsyaml) | Provisioning Service | Needs review |
| [Host capacity resource filters](#host-capacity-resource-filters) | Provisioning Service | Needs review |
| [Site resources and shared lease lifecycle boundaries](#site-resources-and-shared-lease-lifecycle-boundaries) | Provisioning Service | Needs review |
| [Shared host accounting for VM and bare-metal offers](#shared-host-accounting-for-vm-and-bare-metal-offers) | Provisioning Service | Implemented, core storefront/provisioner split pending |
| [Seller-side spot automation](#seller-side-spot-automation) | Provisioning Service | Planned |
| [Multi-Provider Resource Pool Architecture](#multi-provider-resource-pool-architecture) | Provisioning Service | Needs review |
| [`StorefrontCallbackClient` extraction](#storefrontcallbackclient-extraction-conditional) | Provisioning Service | Conditional |
| [Alkahest contracts in baked state](#alkahest-contracts-in-the-baked-state) | Documentation Gaps | Needs review |
| [Symmetric Order Concept](#symmetric-order-concept) | Documentation Gaps | Needs review |
| [Alkahest Escrow Mechanics](#alkahest-escrow-mechanics) | Documentation Gaps | Needs review |
| [SQLite Schema](#sqlite-schema) | Documentation Gaps | Needs review |
| [`negotiation_watchdog`](#negotiation_watchdog) | Documentation Gaps | Needs review |
| [GPU Passthrough Setup](#gpu-passthrough-setup) | Documentation Gaps | Needs review |

> **Structural notes for next TODO pass:**
> - **"Latent Bug Fixes"** section below is an empty placeholder — no items have been filed under it yet. Either populate or remove.
> - **"Known Issues & Areas of Concern"** is a list of operational gotchas, not trackable work items with acceptance criteria. It doesn't map cleanly to table rows (no owner, no completion state). Consider splitting into a separate `KNOWN_ISSUES.md` or converting each entry to a proper task.
> - **Provisioning Service** and **Documentation Gaps** items lack explicit `**Status:**` fields, making their state harder to scan. Should be consistent with the rest of the file.

---

## State Management & Schema Migrations

### Init container migration pattern and schema drift guard

**Problem:** Migration logic runs inside the main service container's startup sequence. A migration failure is indistinguishable from an application crash in Kubernetes pod status (`CrashLoopBackOff` vs `Init:Error`). There is also no runtime guard to catch schema drift when migrations have not been applied — the service can boot silently against a mismatched schema and surface errors only when a query hits a missing column.

**Planned fix:**

For each SQLite service (storefront, provisioning):

1. Add a migration CLI entrypoint to the service — `python -m db.migrate` or a console script — that invokes the same migration logic as a standalone command (same image, different entrypoint). The command should log each migration applied and exit 0 on success.
2. Update each service's Helm Deployment to add an init container using the same image with the migration entrypoint. `Init:Error` is an unambiguous signal that migration failed.
3. Add a schema version guard in the main container's startup code: on startup, read the highest applied migration ID from `schema_migrations`; if it does not match the ID of the last entry in `_MIGRATIONS`, exit with an actionable message:
   ```
   Database schema is at version <current>, service expects <expected>.
   Apply migrations before starting the service:
     docker run <image> python -m db.migrate        (docker / local)
     kubectl apply -f migrate-job.yaml               (Kubernetes without init container)
   ```
   The guard is equally important for non-Kubernetes deployments (local dev, docker-compose) where init containers do not apply.

For the registry (once on Postgres):

4. Implement the Helm pre-upgrade hook Job pattern: a Kubernetes Job runs `alembic upgrade head` as a `helm.sh/hook: pre-upgrade,pre-install` before any Deployment pod sees the new image. If the Job fails, `helm upgrade` errors and the running Deployment is untouched.

---

### Registry: Postgres migration

**Problem:** The registry runs SQLite in all current environments. SQLite on a ReadWriteOnce PVC cannot support concurrent pod versions, which is required for the gradual rollout pattern that preserves client compatibility during non-additive API changes. This blocks any non-additive registry schema or API change until the Postgres infrastructure is in place.

**Context:** The registry codebase already has the migration seams cut — Alembic is the migration framework, `database.py` has an explicit `is_sqlite` branch, and the Postgres engine path has `pool_size=20`. This is not a redesign.

**Planned fix:**

Application-side (`simple-compute-market`):
- Connect `core/registry/src/db/database.py` to Cloud SQL when `database_url` contains a Postgres DSN (the branch already exists; wire the URL from the Helm values)
- Replace the startup `create_all`/stamp bootstrap with an explicit migration-only path suitable for Postgres rollout
- Implement the Helm pre-upgrade hook Job for `alembic upgrade head`

Infrastructure-side (compute-market-internal-infra):
- Add Cloud SQL instance and IAM bindings to the ops repo Terraform modules (see OPS-STORAGE-1 in that repo's planned work)

**Blocks:** Any non-additive change to the registry's schema or HTTP API contract. See `ARCHITECTURE.md` § Registry client compatibility constraint.

---

## Core Stack

### Market Core Extraction follow-ons

**Status:** In progress. The core/kit/domain package split is the current
architecture; stable layout and boundary decisions live in `ARCHITECTURE.md`
→ "Organizing Principle" / "Package layout". This TODO entry tracks only
remaining follow-on work, with design context in
[`design-remaining-work.md`](design-remaining-work.md).

**Remaining work**, in rough dependency order:

1. **Settlement plan shapes** (`design-remaining-work.md` § 2). The
   lifecycle machinery is landed — mechanism-neutral plan carrier,
   `kit/alkahest` claims codecs, seller claims engine, buyer
   `market service`, heartbeat channel, and the
   deferring-third-party-oracle policy (current state:
   `ARCHITECTURE.md` → "Settlement Lifecycle"). What remains are the
   next plan shapes: the oracle *service*, true heartbeat-gated
   collection, interval escrows + penalty bonds (and with them
   engine-driven materialize/reclaim), and eventually a
   `kit/fiat-<provider>` mechanism codec (deferred until a committed
   customer/provider pairing).

2. **Capacity: second executor / second market domain**
   (`design-remaining-work.md` § 3). The site authority, aggregator,
   event split, and two-phase TTL reserve are landed (current state:
   `ARCHITECTURE.md` → "Capacity and the Site Authority"). What
   remains is the multi-domain proof: a job-kind queue keyed by
   `allocation_id`, deal-event routing by recorded `deal_ref`, a
   second executor kind, then a second market-domain storefront
   sharing the pool — plus the parked deployment follow-ons
   (parameterized storefront chart, per-domain build targets).

3. **`storefront-client` wire genericization:** the client wheel still
   sends the flat legacy provision-terms shape
   (`{duration_seconds, ssh_public_key, compute_resource}`) and exposes
   compute-vocabulary parameters. Genericizing it retires the marked
   legacy shim in `market_core.schemas.ProvisionTerms`. Wire-compat
   change; bump client wheels. Rides the carrier-vocabulary
   generalization (`design-remaining-work.md` § 1) so `/negotiate/*`
   churns once.

4. **Buyer CLI residue (small):** render top-level listing `demands`
   wherever listing detail should expose payment constraints; keep
   old-run-log compatibility code clearly marked legacy.

   Deferred remainder from the buyer policy-surface work
   (`ARCHITECTURE.md` → "Buyer negotiation policy surface"):
   - a `BuyerPolicy.prefer(candidates)` hook for policy-driven escrow
     tuple choice among compatible entries — when policies need
     different preferences (today selection takes the first compatible
     entry).

5. **PyPI trusted-publishing one-time setup:** the publish CI
   (`.github/workflows/publish-pypi.yml`) covers the consumable
   packages (kit/core libraries, SDK clients, buyer/storefront plugins,
   the listing registry, provisioning + tokens services, the tokens
   middleware) — every userland role, not the e2e harness/demo/tooling. Names keep the
   `arkhai-` prefix — PyPI orgs don't namespace distribution names, so the
   prefix is the namespace. Each package still needs its PyPI project +
   trusted-publisher environment created per `RELEASING.md` before its
   first publish succeeds (nothing is on PyPI yet).

---

### Gradual typing for core packages

**Status:** Planned.

**Problem:** The `core/` packages are type-friendly but not fully typed or
consistently checked. Most production modules already use annotations and
Pydantic/dataclass carriers, but there is no shared type-checking policy, no
`py.typed` markers in the core wheels, and only `core/registry` has a Makefile
path that invokes mypy. The current dynamic boundaries around generated SDK
clients, Alkahest native objects, JSON wire payloads, and plugin hooks mean API
drift can still escape static checks and surface only in e2e.

**Planned fix:** phase in typing where it most reduces contract drift, without
blocking feature work on a strictness cliff.

1. **Inventory and package markers.**
   - Add `py.typed` to core library/client wheels once each package's exported
     public API is intentionally annotated.
   - Add packaging tests that verify the marker is included in built wheels.
   - Track typed public surfaces package by package: `arkhai-core`,
     `arkhai-core-registry-client`, `arkhai-core-storefront-client`,
     `arkhai-core-buyer`, `arkhai-core-storefront`, `arkhai-kit-site`, and
     `arkhai-core-registry`.

2. **Establish a shared non-strict baseline.**
   - Add a repo-local mypy or basedpyright config for `core/` with pragmatic
     defaults: check untyped function bodies, report missing imports only where
     stubs should exist, and avoid `Any` bans until SDK/client seams are wrapped.
   - Add `uv run` Makefile targets for each core package and one aggregate
     root target.
   - Run the baseline in CI as advisory first, then required once stable.

3. **Tighten carrier and generated-client contracts first.**
   - Make `market_core.schemas` pass a stricter profile before service shells;
     this is the highest-leverage wire contract layer.
   - Tighten registry/storefront client models and method signatures next,
     because downstream packages rely on these as SDKs.
   - Prefer explicit `TypedDict`, Pydantic models, or dataclasses at wire
     boundaries over `dict[str, Any]` where the shape is stable.

4. **Wrap dynamic boundaries instead of leaking `Any`.**
   - Add narrow protocols/adapters for Alkahest SDK objects returned through
     `kit/alkahest` and storefront escrow verification.
   - Type plugin registration hooks and buyer/storefront extension points at
     the trait/protocol level, so domain packages can type-check against the
     contract rather than concrete implementations.
   - Keep raw JSON helpers local to edge modules; normalize into typed carriers
     before crossing core package boundaries.

5. **Ratchet strictness package by package.**
   - Start with `arkhai-core`, registry-client, and storefront-client.
   - Then tighten `kit-site` and `core-storefront` service helpers.
   - Leave FastAPI route modules, SQLAlchemy rows, and migration scripts for
     later; these carry the most framework-driven dynamic typing and lowest
     immediate contract value.
   - Only enable `disallow_untyped_defs` / `disallow_untyped_calls` after the
     package has a clean baseline and typed public API.

**Acceptance criteria:** a fresh checkout can run one aggregate `core` type-check
target with `uv`; all exported core wheels that claim typed support include
`py.typed`; and new SDK/API compatibility breaks in core-facing code are caught
by type checks or focused unit tests before e2e.

---

### Native Launch CLI for Provisioning Service

**Status:** Planned. The registry is launched directly via `arkhai-core-registry` (`make serve`); provisioning has no native launch path.

**Problem:** The provisioning service is launched today only via raw `uvicorn` in its Dockerfile (`domains/vms/provisioning/service/Dockerfile:105`). There is no native, `pip install …` + run path — running it without docker-compose requires manually invoking uvicorn against the right module and managing the worker process separately. This blocks the "provider runs a provisioning service" half of the four-parties topology: a provider should be able to install and run the service on their own machine without inheriting the dev stack's container assumptions.

**Planned fix:** add a `arkhai-vms-provisioning` console script that wraps both the API uvicorn process and the worker process (likely as two subcommands: `arkhai-vms-provisioning serve` and `arkhai-vms-provisioning worker`). Compose / Helm configs then invoke the console script instead of `uvicorn …` directly.

The `arkhai-vms-provisioning` wheel stays its own distributable — it's operated by providers, who already install `arkhai-vms-storefront` from a separate wheel, and the existing Helm chart structure already treats it as a separate workload.

---


**Status:** Planned.

**Problem:** The ARCHITECTURE.md rule prohibits `[tool.uv.sources]` `path` entries containing `../` in any `pyproject.toml`. Such paths bake the monorepo's filesystem topology into `uv.lock`, breaking Docker builds and preventing customers from installing the package outside the checkout. The following packages still have `../` path sources:

**Wheel packages (highest priority — customer-facing):**

- `domains/apicredits/buyer/pyproject.toml` — 5 editable path sources (core, core-buyer, alkahest, config, policy). Domain wheel plugin.
- `domains/vms/buyer/pyproject.toml` — 5 editable path sources (same set). Already has a Makefile; needs sources removal and `reinit` target additions.

**Docker service packages (lower priority — monorepo-root build context makes the referenced paths available inside containers):**

- `core/registry/pyproject.toml` — 1 editable path source (`arkhai-kit-identity`).
- `domains/vms/storefront/pyproject.toml` — 6 editable path sources.
- `domains/apicredits/storefront/pyproject.toml` — 7 editable path sources.
- `domains/apicredits/sample-app/pyproject.toml` — 1 editable path source (`arkhai-apicredits-middleware = { path = "../middleware/python" }`), intra-domain sibling reference.

**Planned fix:** apply the `core/buyer` pattern to each wheel package in priority order: remove `[tool.uv.sources]`, add or update the package Makefile to pass `--find-links $(DIST_DIR)` through `init`, `reinit`, and `test` targets, regenerate `uv.lock`. Service packages follow after the wheel packages are clean.

---

### Storefront DB Pruning

**Status:** Planned. Needs dormant-code verification before any DROP.

**Problem:** The seller-side storefront DB still carries tables that were introduced for the event-driven dispatcher model and may no longer be exercised after the buyer rewrite and the settlement decoupling from `ACCEPT_OFFER`. Candidates in `domains/vms/storefront/.../sqlite_client.py`:

- `decisions` (line 254) and `resource_transition_events` (line 621) — both started life as audit logs; if nothing reads them in production paths they belong in structured logs, not SQLite.
- `policies` (line 229) and `policy_composites` (line 241) — only needed if policies are user-configurable at runtime. If policy is just code (the file-policy discovery flow now in `sync_negotiation._discover_file_policies`), these tables disappear.
- `negotiation_messages` (line 427) — held the per-round message log so a daemon could resume mid-negotiation across restarts. Now that `/negotiate/{new,continue}` is synchronous HTTP and the buyer holds the run-log JSONL, the message log may be dead.

**Planned fix:** for each table, grep for readers (not just writers) outside of test code. If a table is only ever written and never read on a production path, delete the table and its writes. Verify the file-policy discovery flow fully replaces `policies` / `policy_composites` before dropping them. `negotiation_threads` itself stays — it's still the seller's record of an in-flight negotiation.

The `orders → listings` rename is already done; the plan's older framing of "drop the orders mirror" is obsolete (`listings` is the seller's primary entity now, not a registry mirror).

---

### Registry Filter-Spec `indexed: true` Side Indexes

**Status:** Deferred until query latency on `/listings` demands it.

**Problem:** The registry's filter-spec YAML supports an `indexed: bool` annotation per filter (`core/registry/src/api/filter_spec.py:58` — `indexed: bool = False  # reserved for (a2); registry ignores today`). The intent was that hot filter axes (`token`, `gpu_model`) could opt into a registry-side denormalized index — generated column + index for scalar paths, side table for array-projection paths — populated at publish/update time. Today every filter evaluates in-memory via `jsonpath-ng` over the full row set; no side indexes exist, and no filter in `core/registry/filter-spec.yaml` declares `indexed: true`.

**Planned fix:** when query latency on `/listings` starts mattering, wire the `indexed: true` path:
- For scalar JSONPath filters (e.g. `$.offer_resource.gpu_model`): generated column + B-tree index, maintained by the publish/update writer.
- For array-projection filters (e.g. `$.accepted_escrows[*].literal_fields.token`): a side table keyed on `(listing_id, value)`, repopulated on publish/update.
- The evaluator narrows on indexed scalar filters first, then evaluates non-indexed and array-projection filters on the survivor set.

Until then: the `indexed: bool` field stays as a no-op in the loader so the YAML stays forward-compatible. Current row counts make this a non-issue.

---

### Shared Dynaconf Bootstrap

**Status:** Planned. Two copies in the tree today.

**Problem:** `domains/vms/provisioning/service/src/config.py` (~100 LOC) and `e2e-tests/src/settings.py` (~80 LOC) each carry their own near-identical Dynaconf bootstrap (profile selection from `ACTIVE_PROFILES`, `CONFIG_DIRECTORY` resolution, deep-merged `settings.toml` → `.secrets.toml` → `config.yml` → `config-<profile>.yml` → env vars layering). The storefront has since gained its own dynaconf loader at `domains/vms/storefront/src/market_storefront/utils/config.py` with the `STOREFRONT_*` prefix — that one is structurally similar but profile-free, so isn't part of the duplication.

**Planned fix:** lift the shared bootstrap (profile resolution + layered loader factory) into `kit/config` alongside `market_config.config_loader`. `arkhai-vms-provisioning` and `e2e-tests` import from there and pass in their per-service prefix (`PROVISIONING_*` / `ARKHAI_*`) + defaults path. No behavior change; pure dedup.

---

### Move e2e Tests to a Separate Project

**Status:** Planned, no timeline.

**Problem:** `e2e-tests/tests/e2e/` is currently part of this repo. As the stack matures, the e2e suite should move to its own project so it can be run against arbitrary deployments without dragging in the simple-compute-market repo.

**Planned fix:** extract `e2e-tests/` (or just the `e2e/` subtree) to a separate repo. No urgency until external operators want to run the test suite.

---

## Latent Bug Fixes

Genuine pending fixes — distinct from the operational gotchas in the [Known Issues](#known-issues--areas-of-concern) section below, which the current code lives with.

## Known Issues & Areas of Concern

Operational gotchas the current code lives with. Distinct from [Latent Bug Fixes](#latent-bug-fixes) above (which need code changes) and from [Planned Rework](#core-stack) (which needs design + code). Expand as investigation proceeds.

- **Negotiation orphans:** The existence of `negotiation_watchdog.py` implies negotiations can get stuck. The trigger conditions and recovery behavior need documentation.

- **Buyer's initial offer must meet the seller's floor price:** `domains.vms.listings.pricing.extract_initial_price_from_order()` returns `primary_rate_value(accepted_escrows[0])` (already in uint256-domain base units) as the seller's `our_price`. The `BisectionStrategy` in `maximize` direction exits with `"price_unreasonable"` if `their_price < our_price / 1.5`, and does not counter. If the buyer's `BUYER_INITIAL_PRICE` in the e2e test is below this floor, the seller exits at round 0 and `force-accept` returns 409. **Rule:** `BUYER_INITIAL_PRICE >= primary_rate_value(accepted_escrows[0])` in the e2e test constants. Note this only bites where an opening below the listed price is possible — an explicit `--initial-price` or the opt-in `bisection` buyer policy; the default `listed_price` policy opens at the advertised rate, which satisfies the floor by construction.

- **Global pause state persists across e2e test runs:** The storefront's `_GLOBALLY_PAUSED` flag (toggled by `POST /admin/pause` — distinct from per-listing `paused=True`) is in-process memory, not reset between `pytest` sessions. Neither full-deal scenario currently calls global `admin_pause` (storefront integration tests do, but those have their own teardown). The risk is a developer or external script having toggled it manually; the next `/negotiate/new` then 503s with `{"reason": "global"}` regardless of any per-listing state. The `ensure_storefront_resumed` autouse fixture in `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py` mitigates this by calling `admin_resume()` in module teardown. If running against a live environment that may have been left paused, execute `curl -X POST http://localhost:8001/admin/resume -H "X-Admin-Key: <key>"` before running.

- **Resource CSV importer DB path:** `scripts/import_resources_csv.py` resolves the target SQLite path via `--db-path` CLI arg → `STOREFRONT_DB_PATH` env var → `CONFIG.db_path`, in that order. If the importer writes to a different path than the server reads (e.g. via an unset `STOREFRONT_DB_PATH` falling through to a wrong default), the server starts with zero resources and rejects all `/negotiate/new` calls with `409 no_matching_inventory`. `compose/seller.yml` pins `--db-path src/market_storefront/data/storefront/agent.db` explicitly. **Detection:** `GET /api/v1/system/status` exposes `resource_count` as a top-level field; a value of `0` signals this misconfiguration. The smoke test `test_resource_portfolio_seeded` in `test_storefront_smoke.py` asserts `resource_count > 0` and fails with a remediation command.

- **E2e test dependency graph is not mechanically verified:** The `require_state(deal_state, "field")` chain between stages is enforced by convention only. A field set by one stage but not consumed by `require_state` in any downstream stage is a silent gap — the first failure cascades to a skip rather than a fail in the stage that actually needed it. A field name typo in a `require_state` call produces the same symptom: `getattr(deal_state, "nonexistent_field", None)` silently returns `None` and the test skips regardless of pipeline state. **Rule:** when adding a new `DealState` field, always verify that at least one downstream `require_state` call consumes it, and that the field name in `require_state` exactly matches the attribute name on `DealState`. This gap class cannot be caught by unit or integration tests — it is a property of the test's own dependency graph.

---

## Registry Service

### Shared marketplace infrastructure (not per-node)

**Status:** Planned.

**Problem:** The `arkhai-core-registry` is currently deployed as a subchart of the `arkhai-node-operator` Helm chart, implying it is part of every provider node's deployment. In practice the registry is a shared marketplace service — there is one per market, not one per provider. Multiple seller nodes should all register with and publish orders to the same registry instance run by the marketplace operator. Bundling it with the provider chart conflates the marketplace operator role with the provider role.

**Planned fix:** Make `registry` an optional subchart (add `condition: registry.enabled`, default `false`). Provider deployments point at an externally-operated registry via `global.registry.api_url`. Only marketplace operator deployments enable the subchart. Document the two deployment topologies (operator vs. provider) in the Helm `values.yaml` and in `ARCHITECTURE.md`.

---

## Provisioning Service

### Golden image configuration (`management-vars.yaml`)

**Status:** Needs review.

**Problem:** The `golden-image-build` Ansible role writes `management-vars.yaml` to the operator's local machine with root SSH credentials for the golden image. The provisioning service reads these credentials through the standard dynaconf profile system, but the key names in `management-vars.yaml` do not match the names in `settings.toml`.

**What the provisioning service needs from `management-vars.yaml`:**
- `golden_root_ssh_filename` → maps to `settings.golden_root_ssh_filename`
- `golden_root_ssh_password` → maps to `settings.golden_root_ssh_password`
- `golden_image_name` → maps to `settings.golden_image_name`
- `golden_gcs_bucket` and `golden_gcs_project` → in `settings.toml`

**Decision:** The Ansible role should write `management-vars.yaml` keys using the exact names that dynaconf expects (matching `settings.toml`). The operator then includes the relevant keys in the Helm `values.yaml` `config:` block. No separate loader class or file-format adapter is needed.

**Planned fix:** Update `golden-image-build.yml` in `domains/vms/provisioning/iac` to write key names matching `settings.toml` (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`). Document the operator workflow for getting `management-vars.yaml` into the Kubernetes Secret in `domains/vms/provisioning/iac/README.md`.

---

### Host capacity resource filters

**Status:** Needs review.

The host capacity check API should eventually accept optional resource filter parameters (`vcpus`, `ram_mb`, `gpu_count`) and return ranked hosts with sufficient capacity — useful for the storefront's pre-flight check before a `create` job.

---

### Site resources and shared lease lifecycle boundaries

**Status:** Planned.

See `ARCHITECTURE.md` "Lease Lifecycle — allocation-backed watchdog" for the current VM provisioning implementation.

**Problem:** The site authority resource/allocation persistence layer and the lease lifecycle policy layer are still too tightly coupled. A lease is one kind of allocation: it has a start/end time and a watchdog-enforced release path. Other allocation types are plausible, including token allocations, bandwidth allocations, usage-bucket allocations, pod rentals, and bare-metal rentals. The storefront needs to understand leases when it negotiates a time window; a provisioning service needs to understand leases when it enforces that time window. The generic site resource system should not need to understand watchdogs, VM teardown, or lease-specific terminal states.

**Planned fix:** introduce a generic `SiteResourcesService` boundary around the site resource tables and keep it in resource/allocation/event vocabulary. The site resource system can have focused CRUD/state wrappers around each underlying table family:

- `site_resources` — resource inventory and enabled/disabled state.
- `site_allocations` — generic allocation records, allocation state, claim units, opaque metadata, and release state.
- `capacity_events` — anonymous capacity/resource availability deltas for subscribers.

`SiteResourcesService` should understand generic concepts such as `allocation_id`, `resource_id`, state, units/claim attributes, metadata, created/updated/released timestamps, and resource availability events. It should not understand `lease_end_utc`, watchdog cycles, `vm_remove`, VM host/target semantics, `release_failed`, `unmanaged`, or provisioning-specific lifecycle policy.

Lease lifecycle policy should sit above that generic site resource layer. A reusable lease lifecycle service can be moved into a shared wheel by accepting a release delegate/callback for the concrete teardown operation. VM provisioning supplies a `vm_remove` delegate; a pod provisioning service could supply a pod-delete delegate; a bare-metal rental service could supply a node-reclaim delegate. Token or bandwidth allocations might use `SiteResourcesService` without any lease lifecycle layer at all.

**Current state:** VM provisioning has a local `SiteResourcesService` adapter over the existing `market_site` capacity implementation. `LeaseLifecycleService` owns the lease state machine and uses a release delegate so the lifecycle layer is easier to migrate into the shared wheel later. Admin repair routes are available for operator recovery: `POST /api/v1/admin/leases/{lease_id}/retry-release` resubmits the release delegate for `release_failed` leases, and `POST /api/v1/admin/leases/{lease_id}/force-release` releases capacity without teardown proof after manual verification. The force-release route requires an operator reason and can include evidence because it can make capacity available despite incomplete infrastructure cleanup.

**Remaining shared-layer refactor:** narrow the lower `market_site` implementation behind the generic site-resource boundary. The lower implementation still exposes ledger-named and lease-shaped methods; future code should depend on focused site resource/allocation/event service wrappers instead of reaching through those details. Once the lower boundary is generic, move the delegate-based lease lifecycle service into the shared wheel so VM, pod, and bare-metal provisioning services can reuse the state machine with different release delegates.

**Monitoring work:** `release_failed` requires polling the provisioning service or inspecting logs. Add admin monitoring/alerting for failed releases with `lease_id`, resource id, host, VM target, `vm_remove_job_id`, failure reason/message, and suggested recovery actions. Do not notify the storefront with a capacity-released event unless capacity was actually released.

---

### Shared host accounting for VM and bare-metal offers

**Status:** Implemented through transitional VM provisioning packages. The
publication-source interface, VM/bare-metal domain adapters, reusable
core publication command surface, and selected-source composition helpers are
now core/domain-owned. The VM storefront has transitional infrastructure
callback wiring for VM-only, bare-metal-only, or combined VM+bare-metal
publication selections; remaining architectural work is the core storefront
executable/server composition path and moving the multi-domain site provisioner
out of `domains/vms`.

**Goal:** allow a seller to offer the same underlying physical machine as
exclusive bare metal or as VM slices, depending on demand, without double
selling capacity. A bare-metal lease of a host must make all VM slice listings
for that host unavailable. VM slice allocations must make the exclusive
bare-metal listing unavailable until all child allocations are gone.

**Current state:** the VM provisioning service already hosts the site ledger
and is part-way toward the target architecture: `CapacityLedgerService` owns
site resources, allocations, and capacity events; `SiteResourcesService` is a
thin resource/allocation adapter; `LeaseLifecycleService` accepts executor
release implementations. Allocation rows now carry generic executor metadata
(`executor_kind`, `executor_target`, `executor_ref`, `release_job_id`) while
preserving the legacy VM fields. The site ledger also understands
`physical_host_id` plus `allocation_mode` (`shareable` or `exclusive`) resource
attributes for cross-mode conflict checks. A transitional bare-metal domain
adapter now exposes `/api/v1/bare-metal/leases/*` using the
`arkhai-bare-metal` lease models. Lease registration now submits a
queued `node_grant_access` job and stores `create_job_id`; bare-metal release
routes through `executor_kind=bare_metal` and submits `node_reclaim_access`.
Those actions use a separate bare-metal Ansible playbook/role rather than the
VM management role. Internal job payloads now carry domain-neutral
`executor_kind`, `executor_action`, `executor_target`, and `executor_ref`
alongside the legacy `vm_*` aliases; the bare-metal playbook consumes the
neutral values first. The bare-metal domain package owns the access action
vocabulary and minimal grant/reclaim result shape, and now also defines the
first market-lifecycle schema shapes:
`BareMetalListing`, `BareMetalMessage`, `BareMetalTerms`,
`BareMetalMaterialization`, and `BareMetalReceipt`. Conversion helpers adapt
materializations and lease views to the current transitional provisioning API
DTOs. The service package and most operator APIs are still VM-shaped.

**Design stance:** VM and bare-metal provisioning should be separate executor
services, or at least separate executor implementations, but they must not own
separate capacity ledgers for the same hardware. The site authority is the
single source of truth for physical inventory, reservations, conflicts, lease
state, and capacity events. Executor services consume allocation decisions and
report provisioning/release outcomes; they do not independently decide that
shared hardware is available.

The package architecture target is a layered dependency chain:
`core -> domain -> kit/user implementation`, where each layer fills the
dependencies of the layer above and may introduce narrower dependencies of its
own. There is one core API for each role to fit into. Core should define the
market skeleton in terms of injected dependencies: schema codecs,
listing/message/terms/materialization/receipt/result handling, buyer
discovery/aggregation hooks, seller/storefront negotiation and publication
hooks, registry validation hooks, and settlement/provisioning orchestration
slots. Domain packages fill the core role dependencies for one concrete market
and define the deterministic market semantics: the schema shapes plus any
function-like defaults needed to make the market fully specified. Those
defaults may still depend on below-domain interfaces when the market genuinely
requires configurable settlement, identity, capacity, or provisioning
semantics. Kit packages are below-domain dependencies, not universal plugins:
a kit is reusable across domains only when those domains choose compatible
interfaces. User/operator packages may fill remaining policy or infrastructure
slots when the domain intentionally leaves them open.

Domain packages own the schema and deterministic interpretation for their
market semantics: listing payloads, messages, agreed terms, materialization,
receipts, results, provisioning/executor vocabulary, pure validators/codecs,
and schema-implied default/reference behavior. Exact-match seller policy,
exact-proposal buyer helpers, registry filter helpers, canonical fixtures, and
other obvious default implementations may live in the domain package because
they clarify the market's semantics and keep a concrete market usable without
unnecessary extra packages.
Settlement-kit-specific comparison helpers belong with the kit whose payment
vocabulary they inspect; for example Alkahest scalar `best_price`,
`cheapest_first`, and `priceless_last` aggregation policies live in
`market_alkahest.aggregation`, while `core_buyer` owns the aggregation
registry/discovery and schema-opaque control-flow helpers.
Buyer-side discovery should follow the same ownership rule. Domain packages
own domain compatibility filters such as GPU model, region, duration, access
method, service name, or quantity. Kit packages own kit compatibility filters
such as supported settlement mechanism, chain, token, price shape, identity
credential scheme, allowlist/denylist compatibility, and kit-specific local
candidate checks. Core buyer should compose these filters before aggregation
and negotiation rather than baking kit compatibility into each domain plugin.
The current CLI exposes named domain flags plus repeatable `--filter
name=value` passthroughs. The target filter API should first preserve that
surface exactly while replacing repeated flags with one whitespace-separated
string, e.g. `filters="gpu_model=H200 ram_gb_min=range:[32,128]
strict.token=true token=in:[USDC,DAI]"`. This should mirror the registry's
current filter-spec capabilities directly: default equality/membership sugar,
declared `in:[...]`, `not_in:[...]`, `range:[...]`, `exists:true|false`, and
`strict.<filter>=true|false` overrides. Core should parse that string once and
split constraints into registry-side predicates when the registry filter-spec
can serve them and local candidate predicates when the payload is opaque or
kit-specific. Installed domain and kit packages should register filter
vocabulary/compilers for that syntax, so a buyer can combine domain and kit
compatibility constraints without each domain reimplementing every settlement
or identity filter. A more expression-like language with `==`, `and`, or
general infix operators is not the near-term target.
Operator-specific seller policies, buyer policies, provisioning services,
provider integrations, and local service state belong in separate
role/implementation packages that depend on the domain package plus the
relevant core role package. A provisioning service may serve multiple domains
by implementing thin domain adapters over shared local internals, and a domain
may be served by multiple provisioning implementations that all implement the
same domain schema. Reusable substrate such as site authority, allocation
lifecycle, capacity clients, and leased-access helpers belongs in shared kit,
not in one domain's VM-shaped API.
Core role packages should own executable entrypoints consistently across roles;
domain packages should own the role adapters/specs those executables load.
Domain packages can expose extras such as `buyer`, `storefront`, or `registry`
when a role adapter needs dependencies that would otherwise bloat unrelated
users. The current VM and API-credits storefront executable packages are
transitional composition roots; the target is core-owned executables loading
domain adapters.
The core-owned automated publication seam now lives in
`core_storefront.publication_sources.PublicationSource`, with schema-opaque
iteration / single-source execution helpers in
`core_storefront.publication_runner` and entry-point discovery in
`core_storefront.publication_plugins` (`market.storefront_publication_sources`).
VM and bare-metal domain packages fill that seam with lightweight adapters;
concrete storefront composition roots inject local inventory,
registry/storefront publication, and settlement payload callbacks. This
publication source is still narrower than the complete storefront role API: it
covers optional seller automation for "derive local inventory into listings",
not every domain's seller behavior.
API-credits does not currently implement a comparable capacity publication
source because it lacks this VM-style automated inventory path.
The first core-owned storefront domain runtime interface now lives at
`core_storefront.domain_runtime.StorefrontDomainRuntime`; it is a callable
bundle for domain codecs over listing, message, terms, materialization,
receipt, and result payloads. Concrete VM, bare-metal, and API-credits
domain-runtime instances now live with their domain schema code and are wired
through thin storefront composition roots. The next storefront-runtime work is
to make more storefront services consume this core runtime boundary directly
instead of importing domain helpers ad hoc.
The current VM provisioning service still mixes VM contract surface with
generic site-authority substrate; future refactors should split those roles
without breaking existing VM clients. The bare-metal market schema starts under
`domains/bare_metal`; the temporary implementation adapter still lives in
`domains/vms/provisioning/service` until the multi-domain site provisioner is
moved out of the VM domain tree.
The generic market lease lifecycle endpoint now describes release as
executor-dispatched, while `/hosts/{host}/vms/*` remains a direct
admin/operator VM API.

**Required accounting model:**

- Physical machines are represented once in the site authority with stable
  `host_id`/`resource_id`, total units, attributes, supported modes, and
  health/enabled state.
- Allocation `executor_target` values are executor-local identifiers, not a
  shared machine namespace. For VMs this is the VM target/domain; for
  bare-metal this is the bare-metal executor's machine id. Cross-mode
  accounting must use a shared physical identity carried separately, currently
  reserved as `executor_ref.physical_host_id`.
- VM claims consume shareable units from a host, such as GPU count, vCPU, RAM,
  disk, and ports, while the host is not exclusively leased.
- Bare-metal claims require exclusive host ownership and conflict with any held
  allocation on the same host.
- Capacity matching must understand parent/child conflicts: bare metal blocks
  VM slices; VM slices block bare metal; compatible VM slices can coexist while
  unit capacity remains.
- Listings are derived from remaining ledger availability. The storefront
  should publish/reopen/close VM and bare-metal listings from the same capacity
  snapshot rather than from executor-local state.

**Planned fix, before real bare-metal sales:**

1. Move market-managed fulfillment dispatch behind an allocation/executor
   interface keyed by `executor_kind`; VM dispatch calls the existing VM
   provisioner, and bare-metal dispatch calls `node_grant_access` /
   `node_reclaim_access`. The transitional service-side dispatch, neutral
   executor job fields, and separate bare-metal playbook path are landed.
2. Keep direct `/hosts/{host}/vms/*` operator APIs for VM administration, but
   stop treating those APIs as the market-level abstraction for all compute
   fulfillment. The controller/client wording and integration coverage now pin
   `/api/v1/leases/*` as the market-managed lifecycle path whose release
   operation dispatches by `executor_kind`.
3. Add operational hardening around bare-metal access grant/reclaim:
   configurable reclaim policy (landed: `remove_lease_key`, `lock_user`, or
   `delete_user`), host inventory conventions for bare-metal nodes (landed:
   `BareMetalListing.machine_id` / executor target maps to the provisioning
   host registry's `hosts.name`, and inventory import accepts
   `[bare_metal_nodes]` alongside `[kvm_hosts]`), and live-host validation.
   Access grant/reclaim now validates that the machine exists and is enabled
   before queueing Ansible work.
4. Extend listing/publication flows so VM and bare-metal listings are derived
   from the same site-authority snapshot and cross-mode availability. The
   bare-metal domain now provides pure derivation helpers that turn enabled,
   available, `allocation_mode=exclusive` site resources into
   `BareMetalListing` payloads. Bare-metal storefront publication tracking
   primitives and the lightweight storefront publication adapter live in
   `arkhai-bare-metal` under optional role dependencies, so bare-metal
   publication no longer has to be owned by the VM storefront package. The VM
   storefront's publish loop now composes only the VM publication source via
   the core loader. The core loader can discover selected domain publication
   adapters by entry point; the remaining work is a core storefront
   executable/server path that supplies the concrete infrastructure callbacks
   around a selected domain adapter and the same site-authority capacity
   snapshot.
   Cross-mode site-ledger conflict coverage now pins VM-slice versus
   exclusive bare-metal blocking, and
   storefront publication reconciliation coverage now pins close/reopen
   behavior for a dual-mode host. Provisioning integration coverage now drives
   bare-metal lease grant/reclaim jobs through the background job processor and
   verifies that the executor uses the bare-metal playbook. The bare-metal
   seller quickstart now documents live-hardware setup, inventory conventions,
   reclaim policy, validation checks, and publish inspection.

**Acceptance criteria:** one physical host can be registered once, exposed as
both a whole-host bare-metal offer and one or more VM slice offers, and the
site ledger prevents all cross-mode double-sell cases before any executor job
starts.

---

### Seller-side spot automation

**Status:** Planned.

**Current state:** interruptible VM listings can publish splitter-backed
settlement demands, and the storefront has an admin interruption endpoint that
validates an interruptible deal and truncates its capacity lease. The on-chain
splitter declaration and seller automation loop remain separate follow-on work.

**Design stance:** keep the storefront/provisioning HTTP APIs as the public
control surface first. Seller-side spot automation should be configurable, but
does not need to become a protocol-level structured policy API until another
in-protocol participant needs to consume or verify it. In the near term, sellers
can run free implementation code against public endpoints, using shared
middleware/utilities for discovery, safety guards, scoring, dry-runs,
settlement split calculation, and audit logging.

**Public, structured terms vs private automation:** buyer-facing interruption
terms may need a structured listing/negotiation shape earlier than the seller's
private scheduling logic. Public terms include fields such as `interruptible`,
minimum notice, refund formula, protected runtime, preemption limits, and any
penalty or bond semantics. Private automation decides when to interrupt within
those terms, based on seller capacity pressure, fixed-demand opportunity cost,
buyer/account protections, and local operating policy.

**Planned fix:**

1. Add/read missing control-plane views needed by automation: active
   interruptible deals, current allocations, capacity pressure, and dry-run
   interruption plans.
2. Wire the settlement half of interruption: compute/validate splitter amounts
   and submit or prepare the on-chain splitter declaration after capacity lease
   truncation.
3. Ship a seller-side reference runner or library that composes reusable guards
   and scoring helpers over the public API, recording policy name/version,
   config, selected deal, reason, dry-run result, and settlement split in stage
   logs.
4. Promote a formal structured policy/plugin API only after at least two
   materially different seller automation strategies or another in-protocol
   consumer require a stable decision vocabulary.

---

### Multi-Provider Resource Pool Architecture

**Status:** Needs review.

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

A new e2e scenario (addition to `e2e-tests/tests/e2e/`) validates the GCP
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

---


### `StorefrontCallbackClient` Extraction (Conditional)

**Status:** Conditional — only do this if the dependency direction becomes a maintenance problem.

**Problem:** The provisioning service depends on `arkhai-core-storefront-client` for two call sites — the deal-scoped capacity-released notification in `lease_lifecycle_service` (`notify_capacity_released`) and `system_service.get_status()`. This inverts the conceptual layer (provisioning is infrastructure; storefront is a consumer). Not a circular import — `storefront-client` doesn't depend on `arkhai-vms-provisioning` — but the direction is inverted.

**Planned fix (if triggered):** extract the two call sites into a thin client inside the provisioning service wrapping `httpx` directly for the health probe and the deal-event POST. Keeps `arkhai-vms-provisioning` self-contained without a wheel dependency on the storefront layer. May dissolve naturally when deal events route by recorded `deal_ref` (`design-remaining-work.md` § 3).

---

## Documentation Gaps

Items where `ARCHITECTURE.md` has a "TODO: Document X" placeholder. Fill in as part of the next pass on the respective component.

### Alkahest Contracts in the Baked State

**Status:** Needs review.

The exact set of Alkahest contracts deployed in the `dev-env` baked state and their addresses — so operators can wire integrations without reading the deploy scripts.

### Symmetric Order Concept

**Status:** Needs review.

`e2e-tests/.../test_symmetric_orders.py` exercises a "symmetric order" pattern that isn't documented in ARCHITECTURE.md. Document what it is and why it exists.

### Alkahest Escrow Mechanics

**Status:** Needs review.

What on-chain calls Alkahest makes at each point in the negotiation lifecycle: escrow lock, attestation submission, release. Currently the doc only points at the function names.

### SQLite Schema

**Status:** Needs review.

Storefront table definitions, indexes, statefulness/concurrency constraints (single-writer SQLite, negotiation message ordering). The "Storefront DB Pruning" entry assumes a future writer already knows the current layout.

### `negotiation_watchdog`

**Status:** Needs review.

Trigger conditions (staleness threshold), what it writes to the DB, how it interacts with in-flight `/advance` calls. The watchdog's existence is noted but its semantics are not.

### GPU Passthrough Setup

**Status:** Needs review.

Host-hardware constraints, BIOS / kernel module / `iommu` requirements, and the IaC role responsibilities for getting GPU passthrough working on a KVM host.
