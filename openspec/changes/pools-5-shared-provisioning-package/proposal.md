## Why

The original plan (pre-migration `TODO.md` POOLS-5) called for extracting
`AsyncJobQueue`, lease lifecycle/watchdog machinery, provider registry, and
settlement scheduling/fulfillment contracts out of `arkhai-vms-provisioning`
into a new `core/provisioning` (`arkhai-core-provisioning`,
`core_provisioning`) package, so future domain provisioning services would
not depend on a VM-domain package.

**This has been substantially superseded — verified against current code,
not assumed.** A `provisioning/compute/src/compute_provisioning` package
already exists and already owns generic contracts, adapters, pool wire
models, lease lifecycle, and events (`contracts.py`, `adapters.py`,
`pools.py`, `lease_lifecycle.py`, `events.py`, `executor_leases.py`,
`release.py`). `pools-1`'s own design.md recorded moving pool wire models
there instead of a `provisioning_client` package. Separately, there is an
**active, already-drafted** OpenSpec change,
`market-platform-compute-30-extract-service`, whose entire purpose is
moving the remaining generic API assembly, job lifecycle, executor-neutral
lease lifecycle, watchdog scheduling, and capacity mounting from
`domains/vms/provisioning/service` into `provisioning/compute/service` as
an independently deployable service — this is POOLS-5's remaining goal,
already scoped, under a different track.

## What This Change Actually Covers

Given the above, this proposal is narrowed rather than carried forward
verbatim:

- **Do not create a second, competing package.** `core/provisioning` /
  `core_provisioning` as originally named should not be created;
  `provisioning/compute` / `compute_provisioning` is the established
  destination.
- **Residual scope:** once `pools-2` and `pools-3` land, decide whether
  `PhysicalSettlementScheduler`, `FulfillmentProvider`, `ProviderRegistry`,
  and the `SettlementResource`/`SettlementRecord` shapes should move into
  `compute_provisioning` alongside the pool wire models they're adjacent
  to, or stay VM-service-local until a second domain (e.g. `bare_metal`,
  which already exists and already shares the compute-provisioning
  envelope per `physical-provisioning`'s adapter-owned execution
  requirement) actually needs them.
- **Reconcile, don't duplicate, with `market-platform-compute-30-extract-service`.**
  That change is blocked on `market-platform-compute-20-provisioning-contract`
  and covers the job/lease/watchdog/capacity-mount extraction already. This
  proposal's residual scope should land after that cutover, against
  whatever package shape it produces, rather than in parallel.

## Non-Goals

- Anything already covered by `market-platform-compute-30-extract-service`.
- Creating `core/provisioning`/`core_provisioning` under the original name.
- Extracting anything before `pools-2`/`pools-3` exist to extract.

## Activation Condition — partially overridden during `pools-3` implementation

This stays taskless until: (a) `pools-2` and `pools-3` are implemented, and
(b) either a second domain needs `FulfillmentProvider`/`ProviderRegistry`,
or `market-platform-compute-30-extract-service` completes its cutover and
this change's residual scope needs reconciling against the resulting
package shape. Whichever comes first should drive a fresh design-review
pass, not a straight implementation of this document.

**Update**: during `pools-3` implementation, team design review resolved a
separate but related tension — whether `PhysicalSettlementRequest` should be
VM-specific/strongly-typed or a generic cross-domain contract (see
`pools-3`'s `design.md`, "Domain-neutral contracts vs. domain-specific
payloads"). The resolution (generic shared request/resource types, typed
domain-specific payload one layer down) made keeping
`FulfillmentProvider`/`ProviderRegistry` VM-service-local — while the
request/resource types they operate on already lived in the domain-neutral
`compute_provisioning` package — an awkward split. Those two classes (plus
the shared error taxonomy) were moved to `kit/resource-pools` as part of
`pools-3`, ahead of either condition (a)/(b) above being met. The concrete
`FulfillmentService` (VM-domain orchestration) and `AnsibleFulfillmentProvider`
stayed VM-service-local — only the domain-neutral contract moved. This
change's remaining residual scope (if any, once (a)/(b) are met) is
correspondingly smaller than originally written here.

Related: `pools-7-storefront-fulfillment-cutover` (the storefront's
eventual move to the scheduler/provider path) is itself gated in part on
this activation condition, since a cross-service caller is a real argument
for resolving the package boundary rather than staying VM-service-local.
Whichever of the two changes activates first should re-check the other's
Activation Condition/Open Questions before proceeding.

## Capabilities

### Modified Capabilities

None yet — no requirement delta until the activation condition is met and
the reconciled scope is design-reviewed.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` and
  `pools-3-fulfillment-provider`.
- Must be reconciled against `market-platform-compute-30-extract-service`
  (itself blocked on `market-platform-compute-20-provisioning-contract`)
  rather than implemented independently.

## Impact

Not assessed — package boundary and destination depend on how the
activation condition resolves.
