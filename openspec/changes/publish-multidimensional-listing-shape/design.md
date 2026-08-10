# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `vm_offer_resource_for_listing` (`domains/vms/domain/src/arkhai_vms/storefront_adapter.py`)
  constructs `offer_resource` from `pool_id`, `gpu_model`, `gpu_count`, `sla`,
  `region`, plus optional `resource_id`, `interruptible`, and `preemption_notice_seconds`.
- `ComputeResource` (`domains/vms/listings/models.py`) requires `gpu_model`,
  `gpu_count`, `sla`, `region` and declares `vcpu_count`, `ram_gb`, `disk_gb` as
  optional with `None` defaults. The carrier already exists.
- `domains/vms/listings/reconciler.py` reads `resource.get("capacity")` from the
  projection and takes only `gpu_count` from it. The other dimensions are present in
  the source data and dropped in the read.
- `core/registry/filter-spec.yaml` accepts all three fields on `offer_resource` and
  defines `vcpu_count_min`, `ram_gb_min`, `disk_gb_min` with `on_missing: fail`.
- `domains/vms/buyer/buy_cli.py` exposes `--vcpu-min`, `--ram-gb-min`, `--disk-gb-min`.

## Goals / Non-Goals

**Goals:** make declared capacity visible to discovery; change nothing about what the
site authority admits; introduce no vocabulary that a later change must rename.

**Non-Goals:** negotiating, pricing, or reserving on the newly published dimensions.

## Decisions

### Publish what is declared; omit what is not

The alternative — defaulting an undeclared dimension to zero, to the pool's
`default_vm_*` value, or to a host-derived figure — is rejected. The filter
vocabulary already made this decision for the consuming side and recorded the
reasoning: an offer that does not state a spec cannot be assumed to satisfy a
requirement, so a missing field fails closed.

Publishing an inferred value inverts that. `on_missing: fail` treats an omission as
honest ignorance and excludes the listing; a wrong value is treated as a truthful
claim and *includes* it. Under-matching is a discovery inconvenience; over-matching
sells capacity the seller has not declared and surfaces as a fulfillment failure. The
asymmetry is the whole argument.

Pool `default_vm_ram`/`default_vm_vcpus`/`default_vm_disk_size` are especially
tempting here and especially wrong: they are provisioning fallbacks describing what a
VM gets when nothing else says otherwise, not a declaration of what the pool can
serve. Publishing them would advertise a default as a capability.

### The dimension set is whatever the projection declares, not a fixed list

Reading a fixed `("vcpu_count", "ram_gb", "disk_gb")` tuple would need editing for
every future dimension and would silently drop any dimension a domain declares that
the tuple does not name. The publication path copies the declared capacity map,
filtered to the dimensions the domain's own vocabulary recognizes
(`arkhai_vms.DIMENSION_KEYS` today), so a new dimension becomes publishable by being
declared and named in the domain vocabulary rather than by editing publication.

### Naming follows the accepted flattening convention, not a fresh choice

`structured-capacity-requirements`' design records the family-prefixed flat convention
(`gpu.count` → `gpu_count`, `memory.gib` → `memory_gib`) and states explicitly that
inventory fields added ahead of the shared flattening utility should be added in their
already-flattened form. This change follows that instruction rather than making an
independent choice, so nothing published here needs renaming when that change lands.

Where the existing registry field names and that convention disagree — the filter spec
uses `ram_gb` and `disk_gb`, the convention would suggest `memory_gib` and
`storage_gib` — the **existing wire names win for this change**, because they are
already live in the registry schema and the buyer CLI. Reconciling the two is
`structured-capacity-requirements`' job and touches more than publication; introducing
a third spelling here would make that reconciliation harder rather than easier.
Recorded so the discrepancy is a known deferral rather than an oversight.

## Risks / Trade-offs

- **[A pool declares capacity that its provisioning cannot deliver]** → Out of scope
  and unchanged by this change: declaration accuracy is
  `capacity-resource-administration`'s concern. This change publishes declarations
  faithfully and adds no inference of its own.
- **[Listings gain fields before anything negotiates on them]** → Accepted and
  intended. Discovery filters become usable immediately; negotiation follows.
- **[Buyers see a narrower result set once dimensions are published]** → Possible and
  correct: a buyer filtering on RAM currently gets nothing, and afterwards gets the
  listings that actually declare enough. No listing loses a match it legitimately had.

## Migration Plan

Additive; no migration. Existing listings republish with additional fields on the next
reconcile. Rollback is a code revert and republish.

## Open Questions

- **Should the registry's `ram_gb`/`disk_gb` names be reconciled with the
  `memory_gib`/`storage_gib` convention, and by whom?** Deferred to
  `structured-capacity-requirements`, which owns the vocabulary and whose blast radius
  already includes the wire. Deferrable because this change publishes into existing
  names either way, and a rename later is a mechanical follow-up rather than a rework
  of this change's approach.
