## Why

A listing's `offer_resource` is built by `vm_offer_resource_for_listing` from exactly
five fields: `pool_id`, `gpu_model`, `gpu_count`, `sla`, `region` (plus optional
`resource_id` and interruptible markers). vCPU, RAM, and disk are never published,
even though `ComputeResource` declares all three and the projection's per-resource
`capacity` map already reaches the storefront — `_publishable_slices` reads
`resource["capacity"]` and takes `gpu_count` from it, discarding the rest.

Three layers downstream are already built for the dimensions this omission drops:

- `core/registry/filter-spec.yaml` accepts `vcpu_count`, `ram_gb`, and `disk_gb` in
  `offer_resource` and exposes `vcpu_count_min`, `ram_gb_min`, and `disk_gb_min`
  filters.
- Those filters carry `on_missing: fail`, with a documented rationale: an offer that
  does not state a spec cannot be assumed to satisfy a requirement.
- The buyer CLI ships `--vcpu-min`, `--ram-gb-min`, and `--disk-gb-min`.

The consequence is a live defect, not merely a missing capability: **a buyer passing
`--ram-gb-min` today matches zero listings in the market**, because every listing
omits the field and every omission fails closed. Three correct layers are starved by
one omission at publication.

This change is the smallest step toward negotiating full compute capability, and the
only one that delivers value on its own.

## What Changes

- Publish the capacity dimensions a pool's projection actually declares into each
  listing's `offer_resource`, alongside the GPU fields already there.
- Publish what is declared and omit what is not, per dimension. A dimension absent
  from the projection is absent from the listing rather than defaulted, zero-filled,
  or inferred — matching the filter vocabulary's own fail-closed reasoning. An
  inferred value would be worse than an omission, because `on_missing: fail` treats
  omission as honest ignorance while a wrong value silently matches.
- Keep the published shape aligned with the flattening convention
  `structured-capacity-requirements` records as accepted (`gpu.count` →
  `gpu_count`, `memory.gib` → `memory_gib`), so no field published here needs
  renaming when that change's vocabulary lands.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: published listing candidates carry every capacity
  dimension the site projection declares for the underlying resource, and omit
  dimensions the projection does not declare rather than substituting a value.

## Non-Goals

- Do not negotiate on the published dimensions. A buyer naming a shape is still
  rejected by the round-0 guard until `capacity-shape-pricing` and
  `negotiation-driven-capacity-resize` land.
- Do not change the registry filter vocabulary or its `on_missing` semantics; this
  change makes the existing vocabulary reachable.
- Do not add per-dimension pricing. The published shape is descriptive here; pricing
  it is `capacity-shape-pricing`'s scope.
- Do not enumerate additional listings per shape point. The existing
  `for gpu_count in range(1, max_slice + 1)` slice enumeration is unchanged; widening
  it across four dimensions is a combinatorial product and is explicitly not the
  approach.
- Do not change the reservation claim. `compute_capacity_claim_from_order` already
  reads all four dimensions from whatever the order carries and needs no edit.

## Impact

- Affected code: `domains/vms/domain/src/arkhai_vms/storefront_adapter.py`
  (`vm_offer_resource_for_listing`), `domains/vms/listings/reconciler.py`
  (`_publishable_slices` and the slice dictionaries it builds),
  `domains/vms/storefront/src/market_storefront/cli_publish.py`'s offer construction.
- Affected tests: publication unit tests, registry filter integration coverage, and
  at least one e2e path proving a dimension filter now matches a real listing.
- Wire compatibility: additive. `ComputeResource` already declares the three fields as
  optional, and the registry schema already accepts them, so no consumer needs to
  change to tolerate their presence.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change; publication ownership and the
      projection boundary are unaltered.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Published listing candidates carry declared capacity dimensions and omit undeclared
  ones rather than substituting a value —
  `openspec/specs/storefront-publication/spec.md`.

## Dependencies and Related Changes

- **Value depends on `capacity-resource-administration`.** Until capacity
  declarations exist, `capacity_inventory._project_host`'s fallback yields
  `{"gpu_count": N}` only, so this change correctly publishes nothing extra. Its
  correctness does not depend on that change — publish-what-is-declared degrades to
  today's behavior — but its observable benefit arrives when declarations do. Build
  it so that ordering is a non-event.
- Prerequisite for `capacity-shape-pricing`, which prices the shape this change makes
  visible, and touches the same offer-construction path.
- Aligns with `structured-capacity-requirements`' flattening convention; introduces no
  vocabulary of its own.
