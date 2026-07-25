## Why

`pools-2-physical-settlement-scheduler` and `pools-3-fulfillment-provider`
build a generic-scheduling-then-provider-execution path
(`PhysicalSettlementScheduler.select_resource` → `FulfillmentProvider.create`)
inside the extracted compute provisioning service, but **nothing calls it**. The
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
POOLS-7 reconciles these paths by cutting the storefront over to durable
physical-resource scheduling and fulfillment managed by the provisioning
service.

## Current Rebaseline

The shared fulfillment package, multidimensional capacity model, shared feasibility predicate, two provisioning projection families, pull projection endpoints, and storefront in-memory projection loading/polling are now implemented. The production cutover is not: scheduling and fulfillment state remain process-local, provider dispatch is not durably recoverable, the storefront still calls the VM executor path directly, credentials remain persisted, teardown bypasses the provider lifecycle, and pull fulfillment status/results do not exist.

Implementation therefore resumes at the durable lifecycle/persistence work in tasks 3–12. Completed tasks remain recorded in `tasks.md`. Projection production and cache mechanics are no longer POOLS-8 scope; POOLS-8 owns residual durable projection consumption, commercial mapping, and listing hints.

## What This Change Covers

- Change the storefront's ordinary reservation path from host-shaped
  (`vm_host` required attribute) to pool-shaped, consuming
  `pools-4-storefront-capacity-boundary`'s reservation claim shape.
- Replace `create_vm_and_wait_with_credentials`'s direct
  `ExecutorActionEnvelope` dispatch with two provisioning-side calls the
  storefront invokes as separate operations — schedule
  (`PhysicalSettlementScheduler.select_resource`) and begin fulfillment
  (`FulfillmentService.create`) — plus an optional convenience operation
  that composes both for callers that don't need the pricing-preview
  behavior. **`FulfillmentService` does not call the scheduler and never
  will** (`pools-3`'s explicit, unchanged boundary decision); the
  storefront calls them in sequence because `select_resource`'s result
  can be commercially material before a deal is finalized (see
  `design.md`, "Storefront orchestrates scheduling and fulfillment as
  separate calls").
- **Result and credential retrieval is pull-based for this change**:
  `get_fulfillment_status`/`get_fulfillment_result`, read directly from
  durable state, over the existing storefront→provisioning auth
  direction. A push-based delivery transport was designed but requires a
  new provisioning→storefront authenticated channel that doesn't exist
  in this codebase yet — designing that channel is split out to a
  separate change, `provisioning-result-push-delivery`, rather than
  built inside this one. See `design.md`, "`SettlementResult` delivery:
  pull for v1, push deferred to a separate change."
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
  `capacity_reservation_id`. Equivalent retries return the existing fulfillment;
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

This change is active and design-complete. The design review completed on
2026-07-20, and `tasks.md` is the implementation plan for the cutover.

**Resolved scope, superseding the original activation gate below:**
this change retrofits the VM domain storefront and the extracted compute
provisioning service onto the POOLS 1-4 machinery. Compute-30 landed first and
moved service composition to `provisioning/compute/service`, VM/Ansible behavior
to `domains/vms/provisioning/adapter`, and bare-metal behavior to
`domains/bare_metal/provisioning/adapter`; POOLS-7 consumes that layout rather
than performing another service extraction. The shared fulfillment and
physical-settlement lifecycle, persistence, scheduler, provider contracts, and
recovery destination is the new `kit/fulfillment` package decided by this
change's design review. It sits above `kit/site` and `kit/resource-pools` in an
explicit one-way kit dependency hierarchy; authority kits may not import
`market_fulfillment`, deployed services, or domain adapters, including for type
checking. `kit/site` and `kit/resource-pools` may be modified where genuinely
cross-domain, and the `apicredits` domain is explicitly in scope for the same
capacity-reservation-against-a-pooled-view reshape, not just VM.

**Dependencies, current as of this review:**

- `pools-2-physical-settlement-scheduler` — implemented prerequisite.
- `pools-3-fulfillment-provider` — implemented prerequisite.
- `pools-4-storefront-capacity-boundary` — implemented prerequisite.
- `pools-6-multidimensional-fair-scheduling` — implemented prerequisite;
  multidimensional reservation and scheduler fit accounting landed before
  this change begins implementation.
- `pools-8-capacity-projection-and-listing-hints` — related and not blocking. POOLS-7 has already landed projection production, pull endpoints, and in-memory storefront caches; POOLS-8 now owns durable projection generations, explicit mapping into commercial publication/claim data, and listing/TTL hints.
- `market-platform-compute-30-extract-service` — implemented related change;
  it was not a behavioral prerequisite, but was selected to land first, so
  this plan now targets the extracted service and adapter paths.

## Non-Goals

- Anything `pools-4` already covers (claim-shape change itself).
- Kubernetes/cloud/other non-Ansible providers — inherits `pools-3`'s
  Ansible-only scope unless a second domain has forced that open by then.
- Removing `SettlementRecord`/`settlement_claims` independence —
  `pools-3` resolved that boundary; this change should not reopen it
  without new evidence of an actual need to correlate them.
- Durable consumption of Capacity Projections for commercial publication and claim construction, plus operator-declared listing-mode and reservation-TTL hints, remains in `pools-8-capacity-projection-and-listing-hints`. Projection producer endpoints and in-memory cache mechanics already landed here are retained as completed prerequisite work.
- Multi-principal storefront authentication and per-fulfillment-record
  ownership (distinct storefront/tenant principals authenticated separately,
  each scoped to only its own settlement rows). This change's provisioning
  service continues to authenticate its single VM storefront caller as it
  does today. A candidate design surfaced and was rejected as out of scope
  during Section 6's design review (see `dev-branch-migration-notes.md`,
  "Flagged as new, unscoped, cross-cutting work"); it would need its own
  proposal, since it touches every fulfillment API surface and the
  settlement schema, not just one section's caller.
- The bare-metal domain's own fulfillment cutover (bare-metal
  `FulfillmentProvider`, site capacity/config/routing). This change is
  scoped to the VM storefront only, per "Impact" above. A candidate
  implementation surfaced during Section 6's design review is noted in
  `dev-branch-migration-notes.md` for whoever owns that domain's roadmap,
  and is explicitly not part of this change.

## Capabilities

### Modified Capabilities

- `site-capacity`: storefront capacity reservation and fulfillment call
  shape changes to consume the scheduler/provider path.
- `physical-provisioning`: `PhysicalSettlementScheduler` and
  `FulfillmentProvider`/`ProviderRegistry` gain a production caller;
  `pools-2`'s and `pools-3`'s deferred durability/wiring items get
  resolved against a real call shape.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` (implemented) and
  `pools-3-fulfillment-provider` (implemented).
- Requires `pools-4-storefront-capacity-boundary` (implemented).
- Requires `pools-6-multidimensional-fair-scheduling` (implemented).
- Related, not blocking: `pools-8-capacity-projection-and-listing-hints`
  — required for this change's `pool_id`-correctness fix to be complete
  end-to-end on the storefront side; see "Status" above.
- Follows the implemented `market-platform-compute-30-extract-service`
  package layout. Compute-30 did not create `kit/fulfillment` or
  implement this change's durable lifecycle.
- Related, nonblocking follow-on: `provisioning-result-push-delivery` hardens the existing provisioning→storefront callback transport and adds durable result delivery on top of this change's pull-correct durable state.
- `market-platform-bare-metal-10-storefront-composition` consumes the selected-site lifecycle after it lands; it does not block VM cutover.
- `market-platform-compute-40-multi-domain-proof` is the post-cutover regression/topology gate for two storefronts and two provisioning authorities.

## Impact

Touches `kit/site` (`site_resource_pools`/`CapacityReservation` reshape),
`kit/resource-pools` (removal of fulfillment-provider responsibilities),
`kit/fulfillment` (scheduler/policy and provider-contract consolidation,
settlement persistence, recovery, and pull-based result/status query contracts —
push delivery is `provisioning-result-push-delivery`'s scope, not this
change's),
the extracted compute provisioning service (models, migrations, generic
services, API and workers), the VM provisioning adapter (Ansible provider and
release behavior), and the VM storefront's reservation/orchestration path.
POOLS-6 has landed; the result is not fully complete end-to-end without
POOLS-8. The dependency-ordered implementation work is defined in `tasks.md`.
