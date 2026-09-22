## Why

A Resource Pool declares `deliverable_modes`: the offering modes its configured
provider can deliver. `resource-pool-management` is strict about what that means.
An absent or empty set "authorizes no mode and MUST NOT be widened by a default."
An initial set "MUST be derived only from durable provider, playbook, and
registered requirement-delegate configuration that proves the pool can deliver
that mode." A declaration wider than its configuration is narrowed to empty
rather than retained, because an unproved capability is worse than none.

That contract is correct for execution and this change does not weaken it. But it
became the only place a pool says which modes its listings may name, so a seller
who intends no execution integration inherits an execution proof requirement for
an act that involves no execution. Their proved set is empty, empty authorizes
nothing, and they can advertise nothing. The two ways through — fabricating
provider configuration, or declaring a mode the configuration does not prove —
are respectively the pretending this work exists to eliminate and a direct
contract violation that migration would narrow away.

A Resource Pool also has no way to say whether it can be admitted against at all.
Every pool today implicitly can, so the question has never needed asking; supply
traded by private arrangement makes it necessary.

Both are declarations a site makes about a pool, both travel the same policy-tag
channel, both need the same derive-on-upgrade migration, and the second is what
makes the first's safety rule expressible. They belong in one change.

## What Changes

- Add a domain-neutral `advertisable_modes` policy tag declaring the offering
  modes a pool's listings may advertise, validated as a JSON-compatible set of
  unique, non-empty strings. An empty declaration authorizes no mode, and no
  declaration is widened by a default.
- Add a domain-neutral `capacity_backing` policy tag declaring whether a pool can
  be admitted against, with values `backed` and `unbacked`. A malformed value is
  rejected; a discriminator is never resolved to a default. Backing is fixed at
  pool creation.
- Require both tags explicitly on every pool write — create, replace, patch when it
  supplies policy tags, and every definition-document entry. Nothing is defaulted,
  preserved from stored state, or merged. One shared validation serves the typed
  administration models and document import alike.
- Require that a `backed` pool's advertisable set is a subset of its deliverable
  set, rejecting a write that breaks the relation from either side rather than
  repairing it. Require that an `unbacked` pool's deliverable set is empty, which
  keeps it out of every capacity path through the existing execution rechecks; its
  advertisable set is then unconstrained.
- Expose one shared resolver for reading the declarations from projected policy
  tags. It fails closed on malformed values and on either cross-tag violation, and
  reports an absent tag distinctly from a malformed one so a consumer can apply its
  producer-version rule.
- Migrate every existing Resource Pool, in the provisioning service and in the
  API-credits service's own pool storage: overwrite `advertisable_modes` with the
  proved deliverable set and `capacity_backing` with `backed`, reporting each value
  at INFO.
- Refuse to start a service whose seeded or stored pools lack valid declarations,
  naming the pool.
- Require that a producer emitting these tags emits them on **every** pool, so a
  consumer can distinguish an old producer from a producer defect without
  guessing per pool.
- Leave `deliverable_modes` untouched in meaning, derivation, and every execution
  recheck at reservation, scheduling, and provider dispatch.

## Capabilities

### Modified Capabilities

- `resource-pool-management`: a pool declares what its listings may advertise
  separately from what its provider can deliver, and declares whether it can be
  admitted against at all. Both declarations are required on every write. A backed
  pool advertises a subset of what it delivers; an unbacked pool delivers nothing.

### New Capabilities

None.

## Non-Goals

- Do not weaken, widen, or re-derive `deliverable_modes`. Every proof requirement
  and every execution recheck stays exactly as it is.
- Do not change listing behaviour. Storefront-side derivation, listing binding,
  registry publication, and the version-skew rules for reading these tags belong
  to `unbacked-listing-publication`, which also wires this change's shared
  resolver into storefront projection ingestion.
- Do not add a pool read to the site authority. An unbacked pool is kept out of
  admission by its empty deliverable set.
- Do not introduce a publication-only provider kind. That would put a pool in the
  fleet whose provider exists to be never called; a declaration that says nothing
  is safer than an executor that does nothing.
- Do not change how a storefront resolves a listing's offering mode, which comes
  from the frozen contribution registration.

## Impact

- Affected code: the shared resource-pool capability's policy-tag validation and
  typed resolution, pool administration models and service, bulk import and
  validation, canonical export, startup seeding in the provisioning and API-credits
  services, a derivation migration in each, and every in-repository pool writer
  (fixtures, seeds, chart values, definition documents).
- Affected specification: `openspec/specs/resource-pool-management/spec.md`.
- Affected documentation: `docs/development/ARCHITECTURE.md`'s Terms table gains
  capacity-backed and unbacked entries, promoted at this change's closeout —
  because a pool declaring its backing is the point at which the concept becomes
  true.
- Affected operators: a pool gains two required declarations. Migration means no
  existing deployment's advertising surface or admission behaviour changes until an
  operator declares otherwise. Pool API clients and definition documents must carry
  both tags from this change on; a write or an edited document that omits them is
  refused loudly rather than defaulted.
- Not affected: reservation, scheduling, provider dispatch, or any execution
  authorization path. Their rechecks read `deliverable_modes` exactly as before.

## Dependencies and Related Changes

- No blocking dependency.
- **Prerequisite for `unbacked-listing-publication`**, which cannot let an
  execution-less seller advertise anything without the first declaration, and
  cannot derive an unbacked listing without the second.
- Amends a contract established by the archived `pool-declared-offering-modes`
  change. No active change owns that contract, so there was nothing to split a
  minimal piece out of; see `design.md`.
- The POOLS campaign will not resume before this goal completes and is to be
  re-read for consistency when it does, so this amendment does not change a
  contract underneath work in progress.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the Terms table gains capacity-backed
      and unbacked entries, promoted at this change's closeout. Also re-read the
      Resource Pool term and the pool-mode paragraph, which today name
      `deliverable_modes` and its execution rechecks, and decide whether the
      second mode declaration belongs in the permanent map or is subsystem
      detail. Record that disposition either way.
- [x] Existing subsystem specification —
      `openspec/specs/resource-pool-management/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- `capacity-backed` and `unbacked` as defined terms, with backing meaning an
  admission authority exists rather than hardware existing —
  `docs/development/ARCHITECTURE.md#terms`.
- Advertisement authorization and delivery authorization are separate
  declarations — `openspec/specs/resource-pool-management/spec.md`.
- A backed pool's advertisable set is a subset of its deliverable set; an
  unbacked pool's is independent —
  `openspec/specs/resource-pool-management/spec.md`.
- Neither declaration is widened by a default, both are required on every write,
  a malformed backing value fails closed, and a producer emitting these tags emits
  them on every pool — `openspec/specs/resource-pool-management/spec.md`.
- An unbacked pool's deliverable set is empty, which keeps it out of every capacity
  path — `openspec/specs/resource-pool-management/spec.md`.
- Readers of projected declarations resolve them through one shared resolver —
  `openspec/specs/resource-pool-management/spec.md`.
