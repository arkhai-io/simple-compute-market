## Why

Every storefront listing today is capacity-backed. The durable listing binding
requires a trusted site and explicit pool or Physical Resource provenance, its
`site_id` is `NOT NULL`, and the offering mode "must be declared by the selected
Resource Pool". Publication is reconciled against capacity deltas with
close-before-reopen semantics. All of that exists so a listing cannot overstate
what is actually sellable.

A compute seller who wants free discovery, and who will agree terms out of band,
has nothing for any of it to check. Nothing can be reserved, nothing admitted.
Under the current contract that seller has two options, and both are bad:
fabricate a site authority that admits against infinity — a value that admission,
commit, release, and restart recovery would then trust — or stay out of the
marketplace.

Making backing explicit is the third option. It lets an unbacked listing be a
legal shape rather than a special case, keeps the capacity-admission paths honest
by never asking them a question about a listing they cannot answer, and leaves
the seller's supply able to become backed later without a new domain or a
migration that unwinds a fabricated site.

## What Changes

- Carry `capacity_backing` as a declared, projected pool property, a peer of
  `listing_cardinality_mode`. Absent capacity data never implies it.
- Add an explicit backing discriminator to `storefront_listing_bindings`, covered
  by the existing immutability trigger. `site_id` remains `NOT NULL` and
  populated for every listing: it is the listing's *origin* site, which an
  unbacked listing has, because unbacked listings are projected from a site. What
  the discriminator carries is whether that site is an *admission* authority.
- Introduce an unbacked admission provenance alongside `CapacityBinding`, as a
  tagged union. Only code that reserves, commits, releases, schedules, or
  dispatches requires the `CapacityBinding` variant.
- Consume `pool-declared-advertisable-modes`: a listing derived from a pool may
  advertise only a mode that pool declares advertisable. `deliverable_modes` keeps
  its meaning and its execution rechecks untouched.
- Define what an upgraded storefront does with a projection carrying no
  `capacity_backing`: a producer emitting it for no pool is an old producer and
  its pools are interpreted as backed under an explicit, logged, time-limited
  rule; a producer emitting it for some pools and omitting it for one is defective
  and that pool fails closed.
- Implement a backing transition as close-and-republish rather than an in-place
  update, since the durable discriminator is immutable.
- Scope the site-pinned claim-routing requirement, the capacity reconciliation
  loop, and close-before-reopen to capacity-backed listings.
- Keep source-publication reconciliation for every listing. A removed, disabled,
  or changed source declaration must close or update its published listing
  whether or not the listing was backed.
- Publish backing in `offer_resource` and add an exact, fail-on-missing registry
  filter for it, republishing existing listings as explicitly backed so no
  listing relies on an absent field to be classified.

## Capabilities

### Modified Capabilities

- `storefront-publication`: backing is an explicit declared listing property
  distinct from listing origin; the durable binding admits an unbacked admission
  provenance; site-pinned routing and capacity reconciliation are scoped to
  capacity-backed listings; source-publication reconciliation applies to all
  listings; pool advertise-authorization is separated from execute-authorization.
- `registry-discovery`: the compute listing shape carries backing, filterable
  exactly and fail-on-missing.

### New Capabilities

None. This is a posture within existing capabilities, not a new domain.

## Non-Goals

- Do not create a domain, a kit, or a provisioning resource-pool type. Backing is
  orthogonal to what is traded; a domain named for how it settles would be wrong
  on the first hosted-settled unbacked listing.
- Do not publish rates. `publish-indicative-listing-rates` owns the indicative
  rate and its filter, because the rate shape depends on work this change does
  not want to wait on. Discovery without comparison is the acceptance boundary
  here.
- Do not add a settlement mechanism or compose one.
  `compose-contact-exchange-across-compute` owns that, and this change must
  remain true for any mechanism.
- Do not deploy or define a separate registry. Unbacked compute listings carry
  the compute vocabulary and belong in the compute schema identity.
- Do not implement finite unbacked listings or a backing transition on one
  durable listing. Unbacked to backed is close-and-republish; see `design.md`.

## Impact

- Affected code: `core/storefront`'s binding schema and migrations,
  `kit/capacity-publication`'s provenance types and publication runtime, the
  storefront-side projection ingestion, and the compute domains' publication
  candidate derivation.
- Affected specification: `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/registry-discovery/spec.md`, and
  `openspec/specs/site-capacity/spec.md`, whose claim-identity requirement asserts
  unconditionally that a pool-only listing produces a reservation claim.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains a field
  and a filter. Adding filters changes the etag, so buyers re-fetch; the header
  states filters may be added without a version bump.
- Affected data: existing listings are republished carrying explicit
  `capacity_backed`. Without that step an exact filter would exclude them from
  backed queries and a permissive one would include them in unbacked queries.
- Not affected: capacity admission, reservation, scheduling, fulfillment, or any
  provider path. An unbacked listing never reaches them.

## Dependencies and Related Changes

- **Depends on `pool-declared-advertisable-modes`.** Without a declaration that
  authorizes advertising a mode independently of proving delivery, an
  execution-less seller's pool authorizes no mode at all and nothing derived from
  it can advertise anything.
- **Depends on `rename-listing-cardinality-mode`.** Landing the rename first is
  what makes `capacity_backing` and the cardinality hint visibly independent
  rather than looking like one field being widened.
- **Depends on `project-capacity-resources-without-hosts`.** A seller with no
  executor inventory cannot project at all until that lands, and that change also
  scopes the capacity-resource requirement this one relies on.
- **Depends transitively on `capacity-resource-administration`**, through the
  projection change.
- **Prerequisite for `publish-indicative-listing-rates`**, which adds the rate to
  listings this change makes publishable.
- **Completion dependency on `pools-9-retire-local-physical-authority`.**
  Implementation may proceed before it; closeout cannot, because this change's
  promoted architecture text sits alongside the origination statement that change
  owns and makes true. Not a blocking dependency for starting work — a dependency
  for finishing it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the Terms table gains capacity-backed
      and unbacked listing entries, and the "Storefront capacity boundary"
      subsection gains the declared-not-inferred rule and backing's independence
      from cardinality and settlement. These are promoted at this change's
      closeout, when they become true, and not before.
- [x] Existing subsystem specification —
      `openspec/specs/storefront-publication/spec.md` and
      `openspec/specs/registry-discovery/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- `capacity-backed` and `unbacked` as defined terms, with backing meaning an
  admission authority exists rather than hardware existing —
  `docs/development/ARCHITECTURE.md#terms`.
- Backing is declared, never inferred from absent capacity data, and is
  independent of both the cardinality hint and the settlement mechanism —
  `docs/development/ARCHITECTURE.md`, "Storefront capacity boundary".
- A listing's origin site is not its admission authority; the binding carries
  both and they are separate — `openspec/specs/storefront-publication/spec.md`.
- Site-pinned routing and capacity reconciliation are capacity-backed
  requirements; source-publication reconciliation is not —
  `openspec/specs/storefront-publication/spec.md`.
- Pool advertise-authorization is separate from execute-authorization —
  `openspec/specs/storefront-publication/spec.md`.
- Backing is filtered exactly and fail-on-missing —
  `openspec/specs/registry-discovery/spec.md`.
