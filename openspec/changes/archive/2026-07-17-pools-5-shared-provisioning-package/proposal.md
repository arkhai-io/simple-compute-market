# POOLS-5: Shared Provisioning Package — Closed, Absorbed by compute-30

**Status: closed 2026-07-17, without implementation.** This directory is
archived for provenance. It is **not** a record of a completed
implementation the way `2026-07-13-pools-1-resource-pool-foundation` is —
no code changed under this change, and no delta below was ever merged into
a baseline spec. Its residual scope is now owned by
`openspec/changes/market-platform-compute-30-extract-service/`; see that
change's `proposal.md` "Absorbed from POOLS-5" section and `tasks.md` for
the live tracking.

## Original Why

The original plan (pre-migration `TODO.md` POOLS-5) called for extracting
`AsyncJobQueue`, lease lifecycle/watchdog machinery, provider registry, and
settlement scheduling/fulfillment contracts out of `arkhai-vms-provisioning`
into a new `core/provisioning` (`arkhai-core-provisioning`,
`core_provisioning`) package, so future domain provisioning services would
not depend on a VM-domain package.

That was already substantially superseded before this closure — verified
against code, not assumed. A `provisioning/compute/src/compute_provisioning`
package already existed and already owned generic contracts, adapters, pool
wire models, lease lifecycle, and events. `pools-1`'s own design.md recorded
moving pool wire models there instead of a `provisioning_client` package.
`market-platform-compute-30-extract-service` was already scoped, under a
different track, to move the remaining generic API assembly, job lifecycle,
executor-neutral lease lifecycle, watchdog scheduling, and capacity mounting
into that same package — POOLS-5's actual remaining goal.

During `pools-3-fulfillment-provider`'s implementation, `FulfillmentProvider`,
`ProviderRegistry`, and the shared fulfillment error taxonomy were moved to
`kit/resource-pools` — ahead of POOLS-5's activation condition, as a
deliberate override recorded in `pools-3`'s `design.md` ("Domain-neutral
contracts vs. domain-specific payloads"). `PhysicalSettlementRequest`,
`SettlementResource`, `SettlementCandidate`, `SettlementRequirement`, and
`SettlementSchedulingPolicy` (from `pools-2`) already lived in
`compute_provisioning` instead. So by the time of this closure, the
"residual scope" this proposal tracked was down to one open question: should
`kit/resource-pools`'s fulfillment contracts and `compute_provisioning`'s
scheduling contracts be reconciled into one package, and if so, which one.

## Disposition

**Classification:** deferred/conditional work, closed without triggering.

**Rationale:** This proposal's own activation condition — (a) `pools-2`/
`pools-3` implemented, and (b) either a second domain needs
`FulfillmentProvider`/`ProviderRegistry`, or
`market-platform-compute-30-extract-service` completes its cutover — was
re-verified against code on 2026-07-17 during a POOLS-5 design-review
session. (a) is satisfied. (b) is not: `domains/bare_metal` has no
provisioning/fulfillment code yet (storefront-side schema/publication
only), and `market-platform-compute-40-multi-domain-proof`'s proposal
explicitly non-goals generalizing the Ansible provider to bare-metal "solely
for this proof." `market-platform-compute-30-extract-service`'s own
prerequisite (`market-platform-compute-20-provisioning-contract`) is
archived, so compute-30 is unblocked, but its `tasks.md` had not been
started as of this closure.

Separately, `market-platform-compute-30-extract-service`'s own `proposal.md`
already states it "resolves the package-boundary question recorded by
`pools-5-shared-provisioning-package`" — i.e. it had already claimed
ownership of this proposal's entire remaining scope. Carrying both changes
forward in parallel duplicates backlog for the same undecided question,
which `planning-governance`'s "Independently actionable changes" and
"Explicit non-ready states" requirements argue against. Closing POOLS-5 and
folding its scope into compute-30's own design-review pass (which must
happen before compute-30 leaves taskless status regardless) removes that
duplication without losing any information — everything POOLS-5 tracked is
carried forward into compute-30's proposal.

**Evidence:** `market-platform-compute-30-extract-service/proposal.md`
Dependencies section (pre-closure text); `pools-3-fulfillment-provider`'s
`design.md` "Domain-neutral contracts vs. domain-specific payloads" and
`tasks.md` "Corrections from implementation review"; `domains/bare_metal`
directory contents (no provisioning code) as of 2026-07-17;
`market-platform-compute-30-extract-service/tasks.md` (all items unchecked
as of 2026-07-17).

**Destination:** `openspec/changes/market-platform-compute-30-extract-service/`.

**Verification state:** verified against current code on 2026-07-17, not
assumed.

## Original Non-Goals (carried forward as-is to compute-30)

- Do not create `core/provisioning`/`core_provisioning` under the original
  name; `provisioning/compute`/`compute_provisioning` is the established
  destination.
- Do not extract anything before `pools-2`/`pools-3` exist to extract (now
  satisfied).

## Original Dependencies

- Required `pools-2-physical-settlement-scheduler` and
  `pools-3-fulfillment-provider` (both implemented).
- Was to be reconciled against `market-platform-compute-30-extract-service`
  rather than implemented independently — this closure completes that
  reconciliation by merging the two.
