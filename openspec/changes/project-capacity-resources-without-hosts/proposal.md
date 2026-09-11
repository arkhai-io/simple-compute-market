## Why

The resource-pool projection is driven by host rows. `capacity_inventory` builds
a map of capacity resources keyed by host identity, then iterates `Host` rows and
projects one entry per host. A capacity resource with no matching host row
contributes nothing to the projection and is therefore invisible to every
storefront consuming it.

That is a defect against the projection's own stated design.
`capacity_inventory`'s docstring already says "Capacity resources are
authoritative for availability and Physical Resource identity. Host rows supply
only executor inventory needed to correlate the configured machine alias."
`capacity-resource-administration` completes the same direction: it makes `Host`
"executor identity only — addressing, SSH credentials, Ansible alias, pool
membership, enabled state," retires GPU columns as capacity sources, and retires
the host-derived capacity fallback. After that change, capacity resources are the
single authoritative declaration of sellable capacity — and the projection loop
still refuses to see one unless a host exists to carry it.

The gap has no owner. `capacity-resource-administration` redirects what
`_project_host` *reads*; it does not change what the projection *iterates*, and
its own task list reasons in terms of "hosts that previously projected no
`available`". Nothing in `openspec/` describes a hostless capacity resource or a
resource-driven loop.

Closing it matters beyond tidiness. A seller who declares sellable capacity with
no executor host behind it — because delivery is arranged out of band, because
the operator has not configured a connection yet, or because inventory is being
staged ahead of provisioning — currently declares into a void with no error and
no projection entry. The declaration succeeds and nothing happens.

## What Changes

- Invert the projection loop: iterate declared capacity resources and correlate
  host rows in, rather than iterating hosts and looking up resources. A capacity
  resource with no correlated host projects with its declared capacity,
  attributes, and Physical Resource identity, and without executor correlation.
- Keep host-correlated projection behavior identical for every resource that does
  have a host. This change adds entries; it must not alter existing ones.
- Scope the capacity-resource requirement's authority to shape and quantity,
  separating it from whether the declaration can be admitted against. The current
  wording — "a Physical Resource's sellable capacity" — does not survive a
  resource with no correlated host.
- State normatively in `openspec/specs/site-capacity/spec.md` that the capacity
  resource is the unit of projection and that executor correlation is optional
  metadata on a projected entry rather than a precondition for projecting it.
- Define what a hostless entry omits. Executor-correlated fields have no value
  rather than an empty one, matching the existing rule that an absent projection
  and a loaded empty one are distinguishable — a storefront reconciler already
  treats ignorance as different from zero.

## Capabilities

### Modified Capabilities

- `site-capacity`: the capacity resource is the projection unit; executor
  correlation is optional per-entry metadata rather than the iteration key.

### New Capabilities

None.

## Non-Goals

- Do not change what a capacity resource declares, how it is administered, or how
  it is imported. `capacity-resource-administration` owns all three.
- Do not retire the host-derived capacity fallback; that is
  `capacity-resource-administration`'s task, and this change depends on it having
  landed rather than duplicating it.
- Do not add a backing property to the projection.
  `unbacked-listing-publication` owns it. This change makes hostless declarations
  visible; it takes no position on what they mean commercially.
- Do not allow a hostless resource into any execution path. Scheduling, provider
  dispatch, and inventory rendering must continue to require executor
  correlation, and the absence of it must fail closed there rather than
  defaulting.

## Impact

- Affected code: the resource-pool projection in the provisioning service's
  capacity inventory service, and the storefront-side projection ingestion that
  consumes per-entry executor fields.
- Affected specification: `openspec/specs/site-capacity/spec.md`.
- Affected behavior: additive. Deployments with a host for every capacity
  resource see an identical projection.
- Not affected: capacity admission, reservation, scheduling, fairness policy, or
  provider execution.

## Dependencies and Related Changes

- **Depends on `capacity-resource-administration`.** Until capacity resources are
  authoritative for shape across every dimension, inverting the loop would
  project entries whose capacity still had to be derived from the host that, by
  construction, is absent. That change is the one that makes a hostless
  declaration meaningful; this one makes it visible.
- **Prerequisite for `unbacked-listing-publication`**, which needs a seller with
  no executor inventory to be able to project at all.
- Coordinate with `pools-9-retire-local-physical-authority`, which touches
  adjacent projection-consumer surfaces. No ordering dependency either direction.
- `publish-multidimensional-listing-shape` consumes projected dimensions and is
  unaffected by where the loop starts.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — likely no change; the "Site authority"
      section describes what a site owns rather than how its projection iterates.
      Re-confirm at implementation time rather than assuming.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The capacity resource is the unit of projection; executor correlation is
  optional per-entry metadata — `openspec/specs/site-capacity/spec.md`.
- A hostless entry omits executor-correlated fields rather than emptying them, so
  absence stays distinguishable from zero downstream —
  `openspec/specs/site-capacity/spec.md`.
- Execution paths continue to require executor correlation and fail closed
  without it — `openspec/specs/site-capacity/spec.md`.
