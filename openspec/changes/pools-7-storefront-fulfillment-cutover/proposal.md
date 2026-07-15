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
  `ExecutorActionEnvelope` dispatch with a call sequence against
  `PhysicalSettlementScheduler.select_resource` +
  `FulfillmentProvider.create`, polling `get_status` to completion (see
  `pools-3`'s Decision 1a — `create()` is dispatch-only by design).
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
- Decide the `AggregateCapacityClient` placement-policy fate:
  `fill_first`/`most_available` are storefront-side physical-placement
  logic that duplicates what `PhysicalSettlementScheduler`'s round-robin
  policy is meant to own. Likely removed or reduced to pool-level
  preference once the storefront stops picking concrete resources itself.

## Activation Condition

This stays taskless until:

- (a) `pools-4-storefront-capacity-boundary` has landed — the storefront
  needs to already be asking for pool-shaped capacity before it can
  meaningfully call a resource scheduler instead of picking its own
  `vm_host`, and
- (b) either `market-platform-compute-30-extract-service` has completed
  its cutover and `pools-5`'s residual scope has settled where
  `PhysicalSettlementScheduler`/`FulfillmentProvider`/`ProviderRegistry`
  physically live (`compute_provisioning` vs. staying VM-service-local),
  or a second domain forces that decision sooner — whichever comes first.

Starting this cutover before (b) risks wiring the storefront against
integration points that move once the package boundary resolves. A fresh
design-review pass should precede implementation once activated, not a
straight implementation of this document — same posture `pools-5` takes
for its own residual scope.

## Non-Goals (once activated)

- Anything `pools-4` already covers (claim-shape change itself).
- Kubernetes/cloud/other non-Ansible providers — inherits `pools-3`'s
  Ansible-only scope unless a second domain has forced that open by then.
- Removing `SettlementRecord`/`settlement_claims` independence —
  `pools-3` resolved that boundary; this change should not reopen it
  without new evidence of an actual need to correlate them.

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
  `pools-3-fulfillment-provider`.
- Requires `pools-4-storefront-capacity-boundary` to land first.
- Interacts with `pools-5-shared-provisioning-package`'s residual scope
  and `market-platform-compute-30-extract-service` — see Activation
  Condition.

## Impact

Not assessed — scope depends on how `pools-4` and the `compute-30`/
`pools-5` package-boundary question resolve. A future design-review
session should reassess before this leaves taskless status, not implement
this document as written.
