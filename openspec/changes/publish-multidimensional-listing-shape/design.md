# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `vm_listing_resource_for_listing` (`domains/vms/domain/src/arkhai_vms/storefront_adapter.py`)
  constructs `listing_resource` from `pool_id`, `gpu_model`, `gpu_count`, `sla`,
  `region`, plus optional `resource_id`, `interruptible`, and `preemption_notice_seconds`.
- `ComputeResource` (`domains/vms/listings/models.py`) requires `gpu_model`,
  `gpu_count`, `sla`, `region` and declares `vcpu_count`, `ram_gb`, `disk_gb` as
  optional with `None` defaults. The carrier already exists.
- `domains/vms/listings/reconciler.py` reads `resource.get("capacity")` from the
  projection and takes only `gpu_count` from it. The other dimensions are present in
  the source data and dropped in the read.
- `core/registry/filter-spec.yaml` accepts all three fields on `listing_resource` and
  defines `vcpu_count_min`, `ram_gb_min`, `disk_gb_min` with `on_missing: fail`.
- `domains/vms/buyer/buy_cli.py` exposes `--vcpu-min`, `--ram-gb-min`, `--disk-gb-min`.

- **Relevant decisions in `unbacked-listing-publication` (2026-09-23).** The seller's
  inventory guard rechecks every published field sourced from a listing's
  declaration or pool against that listing's own source, and checks availability
  only for capacity-backed listings. The invariant is stated over published fields,
  so each dimension this change publishes extends the guard's coverage with no guard
  change; this change does not need to edit the guard. That change also adopted the
  listing-identity rule and the commitment rule this change's migration plan and
  open question depend on.

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

Additive; no migration. A listing commits only to the fields it publishes, so an
existing listing keeps the shape it was published with and makes no commitment on the
newly published dimensions; they appear on listings published after this change. Until
existing listings are replaced, a buyer's dimension filter matches only the newer ones.
How existing listings come to carry the new fields is part of the listing-identity open
question below. Rollback is a code revert and republish.

## Open Questions

- **Should the registry's `ram_gb`/`disk_gb` names be reconciled with the
  `memory_gib`/`storage_gib` convention, and by whom?** Deferred to
  `structured-capacity-requirements`, which owns the vocabulary and whose blast radius
  already includes the wire. Deferrable because this change publishes into existing
  names either way, and a rename later is a mechanical follow-up rather than a rework
  of this change's approach.

- **How does a listing's identity stay complete once more of the physical resource is
  published, and how does a fungible pool with members of different kinds derive its
  listings?** Raised during `unbacked-listing-publication`'s design, which adopted the
  rule this question builds on: a listing's identity is the physical resource it
  offers — its supply source, offering mode, resource type and subtype, categorical
  attributes such as `gpu_model`, region, and quantities — and everything else
  (price, settlement options, maximum duration, SLA) is a term of sale. A change to a
  term updates the listing in place; a change to the resource is a different listing.

  This change is the first to publish a field that can differ between members of one
  pool, which is what makes the question unavoidable here. Findings, verified
  2026-09-23:

  - The reconciler's structural key is `(site, pool, gpu_count)` for a fungible pool
    and `(site, resource, gpu_count)` for a specific resource. Neither carries the
    resource's kind, so an edit to `gpu_model`, `region`, or a published dimension
    cannot be told apart from the listing it replaces.
  - A fungible pool publishes the first `gpu_model` it encounters among its members,
    and computes `max_member_available_gpu_count` and `available_gpu_count` across
    every member regardless of kind. A pool holding one 8× H100 and one 8× A100
    member publishes 16 GPUs under a single model and leaves the other model's member
    unreachable. Publishing `ram_gb` for a pool whose members declare different RAM
    raises the same "whose value?" question.
  - Admission is already correct. The capacity claim carries `gpu_model`, `region`,
    and the requested dimensions, and the site admits only matching members. The
    defect is confined to the storefront's aggregation.
  - `kit/site` already exports the admission predicate for callers outside the site:
    `dict_resource_satisfies_claim` matches a plain snapshot row against a claim using
    admission's own claim parsing and requirement check. The VM storefront uses it only
    as the `most_available` placement matcher; listing derivation and the seller's
    inventory guard each implement their own matching.

  Proposed direction:

  1. The structural key and the derivation envelope carry a canonical digest of the
     resource's kind, computed over the identity fields the listing publishes. The
     envelope moves to schema version 2 so a replacement listing never collides with
     the immutable binding of the one it replaces. Existing listings do not churn: the
     structural key is recomputed from current data on both sides, and existing
     bindings keep their version 1 envelopes.
  2. A fungible pool's members are partitioned by kind, and each partition derives its
     own slices and availability. A slice is publishable when at least one member
     satisfies that listing's own claim, evaluated with the site's exported predicate,
     so the storefront publishes a slice exactly when the site would admit it, modulo
     the projection's advisory staleness. The same predicate evaluated against declared
     capacity instead of current availability answers the inventory guard's
     declared-match question, leaving one implementation of matching across admission,
     placement, derivation, and negotiation.
  3. A change to the resource's kind then changes the key, so the old listing closes and
     a new one publishes. That is storefront-side migration arrived at through the key
     rather than built as a separate mechanism.

  Sub-questions this direction leaves open:

  - **How does the kind partition treat a dimension one member omits?** Under the
    commitment rule an omitted dimension is no commitment, so a member omitting
    `ram_gb` and a member declaring it are different kinds. The digest must treat
    "absent" as a distinct value rather than as a wildcard, or a listing would commit
    to RAM on behalf of a member that promised none.
  - **What does a slice publish for a dimension it does not enumerate?** A 3-GPU slice
    of a pool mixing 4-GPU/256 GB and 8-GPU/512 GB members needs a rule for its RAM.
    Partitioning by quantity as well as kind avoids the question at the cost of
    splitting listings that are genuinely fungible for GPU count.
  - **Where should the shared predicate live?** It sits in `kit/site`, an authority
    package, and reaches the storefront today by injection as a claim matcher, which
    keeps `domains/vms/listings` and `domains/vms/negotiation` free of the site
    dependency. Moving it to a dependency-light module follows the precedent of the
    CLI query language's shared parser in `market_core.query_dsl`; keeping it and
    injecting it avoids a package move. Either preserves one implementation.
  - **Should the site refuse a mixed-kind fungible pool when a declaration is
    written?** Recommended against. Fungibility is a domain-resolved, optional pool tag,
    so the refusal would need a new site read of pool state, which `ARCHITECTURE.md`'s
    package-layer section says not to add while the existing exception stands. An
    unconditional homogeneity rule would forbid legitimate mixed `specific_resource`
    pools, and storefronts reading sites of other versions must handle heterogeneity
    regardless.

  Interim behavior, owned by `unbacked-listing-publication` and in force until this
  question is resolved:

  - A listing commits only to the fields it publishes. A field it does not publish is
    no commitment: the seller has promised nothing about it, and a buyer receives
    whatever the seller supplies.
  - Source-publication reconciliation refreshes terms of sale on open listings in
    place. It never adds an identity field to a listing that did not publish one,
    because that would make a new commitment under an existing listing identity; the
    dimensions this change publishes therefore appear only on listings published after
    it.
  - A published identity field whose value differs from its source, where the current
    key does not capture that field, closes the listing and reopening is refused while
    the difference persists. The operator's path is a new pool or declaration, as for a
    change of capacity backing. A field the stored listing does not publish is not a
    difference and does not close it.
  - A fungible pool whose members disagree on a published identity field keeps its
    current derivation and logs a warning naming the pool and the fields that differ.

  One further sub-question follows from the commitment rule: **how does an existing
  listing come to carry a newly published field?** If the kind digest is computed over
  the fields each listing itself commits to, adopting the new key churns nothing and
  existing listings never gain the field; they are replaced only when their source
  changes or an operator republishes them. If it is computed over every identity field
  currently publishable, adopting the new key closes each existing listing once and
  republishes it with its full shape under a new identity. The first preserves every
  outstanding buyer reference; the second makes dimension filters complete across the
  catalogue at the cost of one identity change per listing.

  Deferrable because the interim behavior never reinterprets a published listing and
  never publishes a value no member declares. It is not deferrable past this change's
  own closeout if this change publishes a dimension that differs between members of one
  fungible pool: that is the case in which the first-member-wins defect would begin
  publishing wrong quantities rather than only a wrong model.
