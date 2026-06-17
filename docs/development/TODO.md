# Planned Rework

Pending architectural work and known operational issues for the Arkhai market stack. Cross-references `ARCHITECTURE.md` for current-state context.

---

## Index

| Item | Section | Status |
|------|---------|--------|
| [Init container migration & schema drift guard](#init-container-migration-pattern-and-schema-drift-guard) | State Management | Planned |
| [Registry: Postgres migration](#registry-postgres-migration) | State Management | Planned |
| [Market Core Extraction follow-ons](#market-core-extraction--done-remaining-follow-on-work) | Core Stack | In progress |
| [Native Launch CLI for Provisioning Service](#native-launch-cli-for-provisioning-service) | Core Stack | Planned |
| [Escrow Kind Codec Expansion](#escrow-kind-codec-expansion) | Core Stack | Done |
| [Storefront DB Pruning](#storefront-db-pruning) | Core Stack | Planned |
| [Registry Filter-Spec side indexes](#registry-filter-spec-indexed-true-side-indexes) | Core Stack | Deferred |
| [Shared Dynaconf Bootstrap](#shared-dynaconf-bootstrap) | Core Stack | Planned |
| [VM provisioning tombstone cleanup](#vm-provisioning-tombstone-cleanup) | Core Stack | Planned |
| [Storefront Admin CLI Test Coverage](#storefront-admin-cli-test-coverage) | Core Stack | Planned |
| [Move e2e Tests to Separate Project](#move-e2e-tests-to-a-separate-project) | Core Stack | Planned, no timeline |
| [Shared marketplace registry (not per-node)](#shared-marketplace-infrastructure-not-per-node) | Registry Service | Planned |
| [Golden image configuration](#golden-image-configuration-management-varsyaml) | Provisioning Service | Needs review |
| [Host capacity resource filters](#host-capacity-resource-filters) | Provisioning Service | Needs review |
| [Site resources and shared lease lifecycle boundaries](#site-resources-and-shared-lease-lifecycle-boundaries) | Provisioning Service | Needs review |
| [Multi-Provider Resource Pool Architecture](#multi-provider-resource-pool-architecture) | Provisioning Service | Needs review |
| [Flat `client.*` package namespace](#flat-client-package-namespace) | Provisioning Service | Planned |
| [Provisioning smoke tests: use typed client](#provisioning-smoke-tests-use-raw-httpx) | Provisioning Service | Done |
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
> - **"Market Core Extraction follow-ons"** is a single heading containing a numbered list of sub-items with mixed statuses (some done, some planned). Each sub-item is really its own row — worth breaking out as individual `###` entries so their statuses can be tracked independently.
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

### Market Core Extraction — done; remaining follow-on work

**Status:** Done (branch `reorg-market-core-extraction`). The package
graph expresses the core/kit/domain split, distribution names mirror it
(`arkhai-{core,kit,vms}-*`), and the boundaries are enforced by tests
(dependency-direction guardrail, carrier purity, no-plugin buyer CLI).
Current-state layout and decisions: `ARCHITECTURE.md` → "Organizing
Principle" / "Package layout". The remaining architectural items are
planned with their design context in
[`design-remaining-work.md`](design-remaining-work.md). The API-tokens
market domain (second schema plugin, second storefront, tokens service +
middlewares) has since shipped — current state in `ARCHITECTURE.md` →
"API-tokens market domain".

**This list is the single aggregation of what remains**, in rough
dependency order:

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

4. **Schema identity/version for plugins:** *(Done — shipped with the
   API-tokens domain.)* `filter-spec.yaml` gained a `schema: {id,
   version}` header surfaced by the registry client, and
   `resolve_indexer_urls_for_schema` offers each plugin only the
   registries whose declared id matches (lenient on undeclared/
   unreachable). See `ARCHITECTURE.md` → "API-tokens market domain".

5. **Buyer CLI residue (small):** render top-level listing `demands`
   wherever listing detail should expose payment constraints; keep
   old-run-log compatibility code clearly marked legacy.

   Deferred remainders from the buyer policy-surface work
   (`ARCHITECTURE.md` → "Buyer negotiation policy surface"):
   - *(Done — the API-tokens domain fired both triggers.)* The `--yes`
     flag and the `inject_policy_cli_params` invocation moved into core
     (`core_buyer.cli.assume_yes_option` / `register_policy_verb`); the
     per-unit→absolute price translation moved out of the CLI bodies into
     the buyer's negotiation client (`negotiate_with_seller` scales by an
     explicit `unit_count`). The ERC-20 **token-decimals** scaling still
     rides in the VM `buy` body and could follow the same path when
     wanted.
   - a `BuyerPolicy.prefer(candidates)` hook for policy-driven escrow
     tuple choice among compatible entries — when policies need
     different preferences (today selection takes the first compatible
     entry).

6. **PyPI trusted-publishing one-time setup:** the publish CI
   (`.github/workflows/publish-pypi.yml`) now covers all 18 consumable
   packages (kit/core libraries, SDK clients, buyer/storefront plugins,
   the registry indexer, provisioning + tokens services, the tokens
   middleware) — every userland role, not the e2e harness/demo/tooling. Names keep the
   `arkhai-` prefix — PyPI orgs don't namespace distribution names, so the
   prefix is the namespace. Each package still needs its PyPI project +
   trusted-publisher environment created per `RELEASING.md` before its
   first publish succeeds (nothing is on PyPI yet).

---

### Native Launch CLI for Provisioning Service

**Status:** Planned. The registry is launched directly via `arkhai-core-registry` (`make serve`); provisioning has no native launch path.

**Problem:** The provisioning service is launched today only via raw `uvicorn` in its Dockerfile (`domains/vms/provisioning/service/Dockerfile:105`). There is no native, `pip install …` + run path — running it without docker-compose requires manually invoking uvicorn against the right module and managing the worker process separately. This blocks the "provider runs a provisioning service" half of the four-parties topology: a provider should be able to install and run the service on their own machine without inheriting the dev stack's container assumptions.

**Planned fix:** add a `arkhai-vms-provisioning` console script that wraps both the API uvicorn process and the worker process (likely as two subcommands: `arkhai-vms-provisioning serve` and `arkhai-vms-provisioning worker`). Compose / Helm configs then invoke the console script instead of `uvicorn …` directly.

The `arkhai-vms-provisioning` wheel stays its own distributable — it's operated by providers, who already install `arkhai-vms-storefront` from a separate wheel, and the existing Helm chart structure already treats it as a separate workload.

---

### Escrow Kind Codec Expansion

**Status:** Done.

**Current state:** settlement consumes concrete `EscrowTerms` on accept, and every tierable/non-tierable escrow obligation under `alkahest/contracts/src/obligations/escrow` is registered with codec-boundary tests: ERC20, native-token, ERC721, ERC1155, token-bundle, attestation-request, and attestation-UID. Packaged policies include exact-match behavior for non-default formats, and scalar policies cover ERC20, native-token, and ERC1155. Representative compose-backed settlement e2e coverage exists for native-token and ERC1155 escrows.

Follow-up work around schema-packaged registry filters and buyer CLI plugins is tracked under Market Core Extraction.

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

### VM provisioning tombstone cleanup

**Status:** Planned.

**Problem:** `domains/vms/provisioning/` contains review tombstones for deprecated root-level modules. The package root is reserved for the provisioning-service client facade (`client.py`, `__init__.py`), while seller-side VM fulfillment, capacity validation, job-spec construction, and admin payload models belong to the VM storefront package. Shared VM-domain model code belongs in built wheels such as `arkhai-vms-common`, not repository-relative force-includes.

**Planned fix:** after code review, delete the tombstone files (`capacity.py`, `fulfillment.py`, `fulfillment_plan.py`, `job_spec.py`, `storefront_models.py`, and `terms.py`) from `domains/vms/provisioning/`. Keep cross-package dependencies on shared VM-domain code flowing through built wheels in `.dist/`; do not reintroduce repository-relative force-includes for provisioning helpers.

---

### Storefront Admin CLI Test Coverage

**Status:** Planned. Test file was on the original split-plan TODO and never landed.

**Problem:** When the provider subcommands moved from the buyer CLI to `market_storefront.cli`, the provider-side command tests were dropped from `buyer/tests/` and not re-added on the storefront side. `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py` and `test_cli_serve.py` cover slices, but there's no umbrella `test_cli_admin.py` exercising the full subcommand surface.

**Planned fix:** add `domains/vms/storefront/tests/unit/test_cli_admin.py` covering each `market_storefront.cli` subcommand: argument parsing, config-file resolution, the `serve` → `publish` happy path against a mocked storefront, and the error cases for missing wallet / missing config / unreachable chain.

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

**Current state:** VM provisioning has a local `SiteResourcesService` adapter over the existing `core_site` capacity implementation. `LeaseLifecycleService` owns the lease state machine and uses a release delegate so the lifecycle layer is easier to migrate into the shared wheel later. Admin repair routes are available for operator recovery: `POST /api/v1/admin/leases/{lease_id}/retry-release` resubmits the release delegate for `release_failed` leases, and `POST /api/v1/admin/leases/{lease_id}/force-release` releases capacity without teardown proof after manual verification. The force-release route requires an operator reason and can include evidence because it can make capacity available despite incomplete infrastructure cleanup.

**Remaining shared-layer refactor:** narrow the lower `core_site` implementation behind the generic site-resource boundary. The lower implementation still exposes ledger-named and lease-shaped methods; future code should depend on focused site resource/allocation/event service wrappers instead of reaching through those details. Once the lower boundary is generic, move the delegate-based lease lifecycle service into the shared wheel so VM, pod, and bare-metal provisioning services can reuse the state machine with different release delegates.

**Monitoring work:** `release_failed` requires polling the provisioning service or inspecting logs. Add admin monitoring/alerting for failed releases with `lease_id`, resource id, host, VM target, `vm_remove_job_id`, failure reason/message, and suggested recovery actions. Do not notify the storefront with a capacity-released event unless capacity was actually released.

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

### Flat `client.*` Package Namespace

**Status:** Planned. Refactor.

**Problem:** The arkhai-vms-provisioning package exposes its modules at the flat `client.*` level (e.g. `from client.provisioning_client import ...`) because setuptools maps `src/` directly as the package root. To expose a clean `provisioning_service.*` namespace, all internal imports within the package would need to be converted from bare names (e.g. `from models.jobs_model import ...`) to relative imports (e.g. `from .models.jobs_model import ...`).

**Planned fix:** do the relative-imports refactor; switch `service/clients/provisioning.py` to import from `provisioning_service.client.provisioning_client`.

---

### Provisioning Smoke Tests Use Raw `httpx`

**Status:** Done.

The smoke test file (`e2e-tests/tests/smoke/test_provisioning_smoke.py`) already
routes all calls through `SyncProvisioningClient`. Two methods that were
also duplicated on `ProvisioningTestClient` (`pause_watchdog` /
`resume_watchdog`) have been removed from that class; call sites in the
e2e deal scenarios now use `provisioning_client.pause_lease_watchdog()` /
`resume_lease_watchdog()` directly.

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
