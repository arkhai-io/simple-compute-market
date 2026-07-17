## Why

`pools-2-physical-settlement-scheduler` and `pools-3-fulfillment-provider`
build a generic-scheduling-then-provider-execution path
(`PhysicalSettlementScheduler.select_resource` → `FulfillmentProvider.create`)
inside the VM provisioning service, but **nothing calls it**. The
storefront's actual fulfillment path today (verified against current code,
not assumed) is entirely separate:

- `vm_fulfillment_service.py` reserves capacity with
  `required_attributes=("vm_host",)` — the storefront picks the concrete
  physical host **at reservation time**, via `AggregateCapacityClient`
  placement policies (`fill_first`, `most_available` in
  `core_storefront/aggregation.py`).
- It then dispatches straight to the VM executor —
  `provisioning_orchestration_service.create_vm_and_wait_with_credentials`
  submits an `ExecutorActionEnvelope(action_kind="create")` directly via
  `ComputeProvisioningClient` and polls the job itself. This never touches
  `PhysicalSettlementScheduler` or any `FulfillmentProvider`.

So there are two parallel, non-interacting systems today: the one the
storefront actually uses, and the one `pools-2`/`pools-3` are building.
This change is where that gets reconciled — but not yet, and not without
more information than exists in this session. It's recorded now as a
placeholder so a future session has the full context without re-deriving
it.

## What This Change Will Eventually Cover

- Change the storefront's ordinary reservation path from host-shaped
  (`vm_host` required attribute) to pool-shaped, consuming
  `pools-4-storefront-capacity-boundary`'s reservation claim shape.
- Replace `create_vm_and_wait_with_credentials`'s direct
  `ExecutorActionEnvelope` dispatch with two provisioning-side calls the
  storefront invokes as separate operations — schedule
  (`PhysicalSettlementScheduler.select_resource`) and dispatch
  (`FulfillmentService.create`) — plus an optional convenience operation
  that composes both for callers that don't need the pricing-preview
  behavior. **`FulfillmentService` does not call the scheduler and never
  will** (`pools-3`'s explicit, unchanged boundary decision); the
  storefront calls them in sequence because `select_resource`'s result
  can be commercially material before a deal is finalized (see
  `design.md`, "Storefront orchestrates scheduling and dispatch as
  separate calls").
- Resolve `pools-3`'s deferred release-path wiring: give
  `VmReleaseExecutor` (or its replacement) a way to resolve
  `SettlementRecord` → `ProviderRegistry.require(provider).teardown(...)`
  for allocations that went through the settlement path, now that a real
  caller exists to design the call shape against.
- Resolve `pools-2`'s deferred "persist Capacity Settlement Assignments...
  transactionally" follow-on item, now that `select_resource` will have a
  production caller and restart-safety actually matters. Decide then
  whether `PhysicalSettlementScheduler` should write through
  `SettlementRecord` directly or maintain separate assignment storage —
  this was explicitly punted by `pools-3` to avoid scope creep into the
  scheduler while there was no caller to design against
  (`pools-3`'s `design.md`, Risks).
- Add durable database-backed fulfillment idempotency keyed by
  `allocation_id`. Equivalent retries return the existing fulfillment;
  conflicting reuse fails before dispatch. Database uniqueness and
  transactions, not process-local locks, are the correctness mechanism.
  Explicitly handle recovery across the commit/queue-dispatch failure window.
- Snapshot resource-pool provider configuration into executor inputs when the
  fulfillment operation is accepted, and retain enough selected-resource and
  provider metadata for asynchronous teardown after restart.
- Decide the `AggregateCapacityClient` placement-policy fate:
  `fill_first`/`most_available` are storefront-side physical-placement
  logic that duplicates what `PhysicalSettlementScheduler`'s round-robin
  policy is meant to own. Likely removed or reduced to pool-level
  preference once the storefront stops picking concrete resources itself.

## Status

This change is active — a full design review (2026-07-15 through
2026-07-17) resolved the scope and package-boundary questions this
section originally deferred. It is not yet planned (no `tasks.md`); the
next step is planning, not a further design-review pass, unless planning
surfaces a genuine new ambiguity.

**Resolved scope, superseding the original activation gate below:**
this change retrofits the existing VM domain storefront and provisioning
service onto the POOLS 1-4 machinery. It does not perform
`market-platform-compute-30-extract-service`'s service extraction —
where `PhysicalSettlementScheduler`/`DeterministicRoundRobinPolicy` live
was decided directly by this change's design review (moved to
`compute_provisioning`; see `design.md`) rather than waited on. `kit/site`
and `kit/resource-pools` may be modified where genuinely cross-domain,
and the `apicredits` domain is explicitly in scope for the same
capacity-reservation-against-a-pooled-view reshape, not just VM — both
permitted, not required, exercised where this review found real need.

**Dependencies, current as of this review:**

- `pools-2-physical-settlement-scheduler` — implemented prerequisite.
- `pools-3-fulfillment-provider` — implemented prerequisite.
- `pools-4-storefront-capacity-boundary` — prerequisite; verify landed
  status at planning time (see original activation condition below —
  this dependency itself is unchanged, only the compute-30 half of the
  original gate is resolved).
- `pools-6-multidimensional-fair-scheduling` — **blocking prerequisite**,
  found during this review, not part of the original gate: `Host` has no
  memory/disk/vCPU capacity field, so reservation admission cannot verify
  a negotiated shape fits any real machine. See `design.md`, "Dependency
  on POOLS-6." This change's reservation-admission work must not begin
  implementation until `pools-6` resolves multidimensional capacity
  tracking.
- `pools-8-capacity-projection-and-listing-hints` — related, not
  blocking, but consequential: this change alone fixes
  provisioning-service-side `pool_id` correctness; the storefront's own
  claim-building isn't fixed until `pools-8` also lands. See `design.md`,
  "Scope split: `CapacityProjection` and hints move to `pools-8`."
- `market-platform-compute-30-extract-service` — related follow-on, not
  an activation prerequisite or blocker.

**Original activation condition (superseded above, kept for history):**

This stayed taskless until:

- (a) `pools-4-storefront-capacity-boundary` has landed — the storefront
  needs to already be asking for pool-shaped capacity before it can
  meaningfully call a resource scheduler instead of picking its own
  `vm_host`, and
- (b) either `market-platform-compute-30-extract-service` has completed
  its cutover and settled where `PhysicalSettlementScheduler`/
  `FulfillmentProvider`/`ProviderRegistry` physically live
  (`compute_provisioning` vs. staying VM-service-local — see that change's
  "Absorbed from POOLS-5" section, formerly tracked by the now-closed
  `pools-5-shared-provisioning-package`), or a second domain forces that
  decision sooner — whichever comes first.

(b) was resolved directly rather than waited on, per "Resolved scope"
above.

## Non-Goals (once activated)

- Anything `pools-4` already covers (claim-shape change itself).
- Kubernetes/cloud/other non-Ansible providers — inherits `pools-3`'s
  Ansible-only scope unless a second domain has forced that open by then.
- Removing `SettlementRecord`/`settlement_claims` independence —
  `pools-3` resolved that boundary; this change should not reopen it
  without new evidence of an actual need to correlate them.
- **Operator-declared listing-mode hints, and `CapacityProjection`
  (the storefront's pool/capacity mirror they depend on), are fully out
  of scope — moved to `pools-8-capacity-projection-and-listing-hints`.**
  Originally this change's proposal required listing-mode hints be on
  this change's design-review agenda before implementation; that review
  happened, and its conclusion was to split this work out entirely
  rather than design it here, given its size and separability from the
  fulfillment-cutover mechanics. See `design.md`, "Scope split:
  `CapacityProjection` and hints move to `pools-8`" for the consequence
  this split has for this change's own `pool_id`-correctness fix.

## Capabilities

### Modified Capabilities (once activated)

- `site-capacity`: storefront capacity reservation and fulfillment call
  shape changes to consume the scheduler/provider path.
- `physical-provisioning`: `PhysicalSettlementScheduler` and
  `FulfillmentProvider`/`ProviderRegistry` gain a production caller;
  `pools-2`'s and `pools-3`'s deferred durability/wiring items get
  resolved against a real call shape.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` (implemented) and
  `pools-3-fulfillment-provider` (implemented).
- Requires `pools-4-storefront-capacity-boundary` to land first.
- **Requires `pools-6-multidimensional-fair-scheduling`** — blocking
  prerequisite for reservation-admission work; see "Status" above.
- Related, not blocking: `pools-8-capacity-projection-and-listing-hints`
  — required for this change's `pool_id`-correctness fix to be complete
  end-to-end on the storefront side; see "Status" above.
- Interacted with `market-platform-compute-30-extract-service`'s absorbed
  package-boundary decision (formerly tracked by the now-closed
  `pools-5-shared-provisioning-package`) — resolved directly by this
  change's design review rather than waited on; see "Status" above.

## Impact

Touches `kit/site` (`site_resource_pools`/`CapacityReservation` reshape),
`compute_provisioning` (scheduler/policy relocation, `SettlementRecord`),
the VM provisioning service (models, migrations, services, release
lifecycle), and the VM storefront's reservation/orchestration path.
Blocked on `pools-6` for reservation-admission correctness; not fully
complete end-to-end without `pools-8`. Detailed file-level impact is a
planning-step output, not assessed further here — this section will be
revised once `tasks.md` exists.
