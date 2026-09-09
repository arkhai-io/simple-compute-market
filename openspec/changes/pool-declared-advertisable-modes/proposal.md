## Why

A Resource Pool declares `deliverable_modes`: the offering modes its configured
provider can deliver. `resource-pool-management` is strict about what that
declaration means. An absent or empty set "authorizes no mode and MUST NOT be
widened by a default." An initial set "MUST be derived only from durable
provider, playbook, and registered requirement-delegate configuration that proves
the pool can deliver that mode." A declaration wider than its configuration is
narrowed to empty rather than retained, because an unproved capability is worse
than none.

That contract is correct and this change does not weaken it. But it leaves a
seller who intends no execution integration with no way to advertise anything. A
seller offering VM capacity they will deliver by private arrangement has no
Ansible playbook and no requirement delegate, so the proved set is empty, so the
pool authorizes no mode, so nothing derived from it can advertise `vm`.

The two ways out without this change are both bad. Fabricating provider
configuration to satisfy the schema recreates exactly the kind of pretending
Goal 7 exists to eliminate, and it puts a pool into the fleet that a dispatch path
might one day believe. Declaring a mode the configuration does not prove violates
the contract directly and would be narrowed away by its own migration rule.

The missing distinction is that permission to *advertise* a mode and permission to
*deliver* one are different claims. A pool that proves it can deliver VMs has
made both; a pool that intends an out-of-band arrangement makes only the first.

## What Changes

- Add a domain-neutral `advertisable_modes` policy tag declaring the offering
  modes a pool's listings may advertise, validated by the shared resource-pool
  capability the same way `deliverable_modes` is: a JSON-compatible set of
  unique, non-empty strings, with an absent or empty declaration authorizing no
  mode and never widened by a default.
- Require that a capacity-backed pool's advertisable set is a subset of its
  deliverable set. A pool that can be admitted against must not advertise a mode
  its provider cannot deliver.
- Leave an unbacked pool's advertisable set independent of its deliverable set,
  which will ordinarily be empty. Advertising is a claim about what is offered,
  not about what the provider can execute.
- Derive an existing pool's initial advertisable set from its proved deliverable
  set, so no pool's advertising surface changes on upgrade.
- Leave `deliverable_modes` untouched in meaning, derivation, and every execution
  recheck at reservation, scheduling, and provider dispatch.

## Capabilities

### Modified Capabilities

- `resource-pool-management`: advertisement authorization is declared separately
  from delivery authorization, constrained to a subset of it for pools that can
  be admitted against.

### New Capabilities

None.

## Non-Goals

- Do not weaken, widen, or re-derive `deliverable_modes`. Every proof requirement
  and every execution recheck stays exactly as it is.
- Do not make either declaration imply backing. Backing is declared separately;
  this change only stops advertisement from requiring an execution proof.
- Do not change how a storefront resolves a listing's offering mode, which comes
  from the frozen contribution registration.
- Do not introduce a publication-only provider kind. That would put a pool in the
  fleet whose provider exists to be never called; separating the two declarations
  is the smaller change.

## Impact

- Affected code: the shared resource-pool capability's policy-tag validation and
  typed resolution, pool administration and bulk import, the projection, and the
  canonical export.
- Affected specification: `openspec/specs/resource-pool-management/spec.md`.
- Affected operators: a pool gains a second mode declaration. Derivation from the
  proved deliverable set means an existing deployment sees no behavioral change
  until an operator declares otherwise.
- Not affected: reservation, scheduling, provider dispatch, or any execution
  authorization path.

## Dependencies and Related Changes

- No blocking dependency. This is a self-contained addition to the pool policy-tag
  channel and is independently valuable: the distinction it draws is real whether
  or not unbacked listings ever exist.
- **Prerequisite for `unbacked-listing-publication`**, which cannot let an
  execution-less seller advertise anything without it.
- Amends a contract established by the archived
  `pool-declared-offering-modes` change. No active change owns that contract, so
  there is nothing to split; see `design.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — the "Resource Pool" term and the
      pool-mode paragraph name `deliverable_modes` and its execution rechecks.
      Re-confirm at implementation time whether the second declaration needs a
      mention there or whether it is subsystem detail; do not assume either.
- [x] Existing subsystem specification —
      `openspec/specs/resource-pool-management/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Advertisement authorization and delivery authorization are separate
  declarations — `openspec/specs/resource-pool-management/spec.md`.
- A capacity-backed pool's advertisable set is a subset of its deliverable set —
  `openspec/specs/resource-pool-management/spec.md`.
- Neither declaration is widened by a default, and an existing pool's initial
  advertisable set derives from its proved deliverable set —
  `openspec/specs/resource-pool-management/spec.md`.
