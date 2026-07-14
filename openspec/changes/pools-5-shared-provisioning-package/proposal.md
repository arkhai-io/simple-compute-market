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

## Activation Condition

This stays taskless until: (a) `pools-2` and `pools-3` are implemented, and
(b) either a second domain needs `FulfillmentProvider`/`ProviderRegistry`,
or `market-platform-compute-30-extract-service` completes its cutover and
this change's residual scope needs reconciling against the resulting
package shape. Whichever comes first should drive a fresh design-review
pass, not a straight implementation of this document.

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
