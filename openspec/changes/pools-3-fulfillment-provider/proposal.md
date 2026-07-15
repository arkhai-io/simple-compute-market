## Why

The provisioning service has no formal abstraction separating physical
settlement *operations* from lifecycle and job-management machinery.
`pools-2-physical-settlement-scheduler` selects a `SettlementResource` but
nothing yet executes against it, and `pools-2` explicitly defers durable
storage of that binding. Without a provider boundary, future domain
provisioning services would have to duplicate VM-domain execution code or
depend on it directly.

`pools-2` is implemented (verified against
`services/physical_settlement_scheduler.py` and its
`_capacity_settlement_assignments` map) except for the follow-on items its
own `tasks.md` lists as remaining work. This change adds durable
`SettlementRecord` persistence for the *fulfillment* side (provider
execution state) but deliberately does not touch
`PhysicalSettlementScheduler`'s own non-durable assignment map — see
"Explicitly Deferred This Round." Caller wiring (something actually
invoking `select_resource` + `create`) also remains unscoped — see
`pools-7-storefront-fulfillment-cutover`.

## What Changes

- Define `FulfillmentProvider` (ABC), `FulfillmentResult`, and
  `ProviderStatus` in the VM provisioning service. A provider receives an
  already-selected `SettlementResource` and performs `create`/
  `get_status`/`teardown` against it; it MUST NOT independently select or
  substitute a different resource.
- `create()` is **dispatch-only, not blocking-to-completion**. Ansible
  execution runs through the existing `AsyncJobQueue`/`AnsibleJobService`
  background worker (can take minutes); `create()` submits the job and
  returns a `FulfillmentResult` carrying a job reference and a `pending`
  provider-metadata state. `get_status(...)` polls the underlying job and
  is how a `pending` record is observed to move toward `active` (or
  `failed`). Whatever eventually calls `create()` is responsible for
  polling — same shape as the existing `LeaseRegistration.create_job_id`
  pattern already used elsewhere in this service.
- Add durable `SettlementRecord` persistence, extending the same binding
  identity `pools-2` establishes (`allocation_id`) rather than creating a
  second, competing record — `pools-2` is deliberately non-durable and this
  is where that persistence lands. `SettlementRecord.state` tracks
  `pending` / `active` / `failed` (teardown moves a record out of the live
  set entirely rather than adding further states here).
- Implement `AnsibleFulfillmentProvider` around the existing
  `AnsibleJobService`/`AnsibleService`. Per-pool Ansible configuration is
  **not new storage** — `AnsiblePoolConfig` (`playbook_path`,
  `inventory_group`, `extra_vars`) already persists per pool and is already
  resolvable via `ResourcePoolService.get_pool(pool_id).provider_config`
  (see `AnsiblePoolConfigHandler`, wired in `container.py` today). The
  provider reads that, builds Ansible variables, dispatches through the
  existing job queue, normalizes results, and extracts credentials for the
  selected resource. It owns execution, not placement.
- Keep `ProgrammableMockAnsibleService`'s `mockMode`-flag test seam inside
  the Ansible provider (selected in `_make_ansible_service`); do not
  promote it to the `FulfillmentProvider` level.
- Implement `ProviderRegistry.require(provider)`, constructed in the DI
  container at startup, mapping provider strings to `FulfillmentProvider`
  instances. Lifecycle code stays free of provider-specific branches.

## Explicitly Deferred This Round

- **No rewiring of `LeaseLifecycleService`'s release path.** The
  lifecycle's actual injection point is `executor_release:
  ExecutorReleasePort`, dispatched by `ExecutorReleaseDispatcher` on
  `allocation["executor_kind"]` (`vm` / `bare_metal`) to
  `VmReleaseExecutor` / `BareMetalReleaseExecutor` — not a
  `release_delegate` parameter as earlier drafts of this document said.
  `VmReleaseExecutor` is today a narrow, VM-specific Ansible caller
  (`vm_action="vm_remove"`) with no notion of `SettlementResource`,
  `pool_id`, or `provider`; `ProviderRegistry` dispatches on `provider`
  (mechanism), an orthogonal axis to `executor_kind` (domain allocation
  semantics — VM-shareable vs. bare-metal-exclusive; see
  `market-platform-compute-40-multi-domain-proof`). Because nothing calls
  `select_resource` + `create` yet, no `SettlementRecord` rows will exist
  by the end of this change, so there is nothing live for
  `VmReleaseExecutor` to release through the registry. Wiring that
  connection now would be dead code. It's deferred to whichever change
  first gives `SettlementRecord` a real caller (see
  `pools-7-storefront-fulfillment-cutover`), where it can be designed
  against an actual call shape instead of guessed at.
- **No change to `PhysicalSettlementScheduler`.** `select_resource()` has
  no production caller today (only tests call it), so `pools-2`'s
  "persist Capacity Settlement Assignments... transactionally" follow-on
  item is deliberately left alone rather than folded into this change's
  `SettlementRecord` work — that would mean reaching into the scheduler's
  internals for a durability need nothing is exercising yet. Deferred to
  `pools-7-storefront-fulfillment-cutover`.

## Non-Goals

- Kubernetes, cloud, storage, power, or bandwidth providers — Ansible only.
- Recreating the removed generic `provisioning_client` package.
- Any storefront-side change (`pools-4`, `pools-7`).
- Extracting these contracts into a shared package (`pools-5` — conditional
  on a second domain actually needing them, or on
  `market-platform-compute-30-extract-service` landing first).
- Rewiring `LeaseLifecycleService`/`ExecutorReleaseDispatcher`/
  `VmReleaseExecutor` to consult `ProviderRegistry` — see "Explicitly
  Deferred This Round."

## Settlement Record / Claims Boundary (resolved)

`SettlementRecord` (provisioning-side, physical-settlement state, keyed on
`allocation_id`) and the storefront's `settlement_claims` /
`mechanism_state` in `ClaimsEngine` (`core/storefront/settlement_lifecycle.py`,
seller-side on-chain claim collection, keyed on `claim_ref`) are confirmed
independent: `ClaimsEngine` has no notion of `allocation_id`, `pool_id`, or
physical resources today, and drives arbitrary settlement-plan obligations
through injected `check_conditions`/`collect` mechanism hooks with no
physical-provisioning awareness. `SettlementRecord` MUST NOT reference
`settlement_claims`/`ClaimsEngine` in this change. If a future change needs
to correlate physical settlement with claim collection, that is new,
separately-proposed work — not something to guess at here.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: adds `FulfillmentProvider`, `ProviderRegistry`,
  and durable `SettlementRecord` persistence extending the `pools-2`
  binding.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` (implemented; this
  change adds the durable settlement record for fulfillment, not the
  scheduler's own separate "persist assignments" follow-on item — see
  "Explicitly Deferred This Round").
- Independent of `pools-4-storefront-capacity-boundary` (neither requires
  the other).
- Precedes `pools-7-storefront-fulfillment-cutover`, which is the change
  that will eventually give `select_resource`/`create` a real caller and
  revisit both deferrals above.
- `pools-5-shared-provisioning-package`'s residual scope (extracting these
  contracts to a shared package) is conditional on this change landing
  first, and on reconciling against `market-platform-compute-30-extract-service`.

## Impact

- **Packages:** `domains/vms/provisioning/service` (provider, registry,
  persistence). Stays VM-service-local per `pools-5`'s guidance — no
  change to `provisioning/compute` this round.
- **Database:** new durable settlement-record storage, extending
  `pools-2`'s binding identity rather than adding a second table for the
  same key.
- **API:** none new required by this change alone; no caller invokes
  `select_resource`/`create` yet — see `pools-7`.
- **Compatibility:** existing `AnsibleJobService`/`AnsibleService` tests
  must pass unchanged — this change wraps, not replaces, that machinery.
  `LeaseLifecycleService`/`ExecutorReleaseDispatcher` are untouched.
