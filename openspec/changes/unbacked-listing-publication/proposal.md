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

- Consume `capacity_backing` from the projection. The **projected pool tag** is read
  live at each point of need and is never cached as storefront-local inventory, like
  every other policy tag. The **listing's backing discriminator**, derived from it at
  publication, is durable and immutable on the binding. Those are different things
  and the distinction is load-bearing: caching the pool tag would make the storefront
  an authority on a site fact, while deriving the discriminator per read would let a
  bound listing change category. Absent capacity data never implies either; the pool
  declaration and its migration belong to
  `pool-declared-advertisement-and-backing`.
- Add an explicit backing discriminator to `storefront_listing_bindings`, covered
  by the existing immutability trigger. `site_id` remains `NOT NULL` and
  populated for every listing: it is the listing's *origin* site, which an
  unbacked listing has, because unbacked listings are projected from a site. What
  the discriminator carries is whether that site is an *admission* authority.
- Introduce an unbacked admission provenance alongside `CapacityBinding`, as a
  tagged union. Only code that reserves, commits, releases, schedules, or
  dispatches requires the `CapacityBinding` variant.
- Consume `pool-declared-advertisement-and-backing`: a listing derived from a pool may
  advertise only a mode that pool declares advertisable. `deliverable_modes` keeps
  its meaning and its execution rechecks untouched.
- Define what an upgraded storefront does with a projection carrying neither new
  pool tag. A producer emitting a tag for no pool predates it: `capacity_backing`
  resolves to backed, and `deliverable_modes` serves as advertisement
  authorization — each reproducing the old contract rather than defaulting
  permissively, under an explicit, logged, time-limited rule. A producer emitting a
  tag for some pools and omitting it for one is defective and that pool fails
  closed. A malformed `capacity_backing` value fails that pool closed as well.
- Implement a backing transition as close-and-republish rather than an in-place
  update, since the durable discriminator is immutable.
- Scope the site-pinned claim-routing requirement, the capacity reconciliation
  loop, and close-before-reopen to capacity-backed listings.
- Keep source-publication reconciliation for every listing. A removed, disabled,
  or changed source declaration must close or update its published listing
  whether or not the listing was backed.
- Publish backing in `offer_resource` and add an exact, fail-on-missing registry
  filter for it, republishing existing listings as explicitly backed so no listing
  relies on an absent field to be classified.
- Refuse a source declaration carrying no quantity where derivation needs one,
  rather than substituting a default that would be indistinguishable in the
  published listing from a declared shape. Publish no second field describing how
  strong a listing's shape claim is: every published field is a seller assertion on
  every listing, and the exhaustibility difference is already carried by the
  published backing value.

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
- Do not publish rates. `publish-indicative-listing-rates` owns the seller's
  asking rate and its filters, because that surface has its own asset, period,
  filter-grammar, and seller-authoring decisions — not because its shape waits on
  other work. Discovery without comparison is the acceptance boundary here.
- Do not add a settlement mechanism or compose one.
  `compose-contact-exchange-across-compute` owns that, and this change must
  remain true for any mechanism.
- Do not deploy or define a separate registry. Unbacked compute listings carry
  the compute vocabulary and belong in the compute schema identity.
- Do not implement finite unbacked listings or a backing transition on one
  durable listing. Unbacked to backed is close-and-republish; see `design.md`.

## Impact

- Affected code: `core/storefront`'s binding schema and migrations,
  `kit/capacity-publication`'s provenance types, publication runtime, and the
  `PublicationDomainHooks` protocol, the storefront-side projection ingestion, the
  VM negotiation runtime's binding guards, and both the VM and API-credit domains'
  publication candidate derivation and capacity clients. API-credit behaviour does
  not change — it is capacity-backed by a quota resource — but its types move with
  the protocol.
- Affected specification: `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/registry-discovery/spec.md`, and
  `openspec/specs/site-capacity/spec.md`, whose claim-identity requirement asserts
  unconditionally that a pool-only listing produces a reservation claim.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains a field
  and a filter. Adding filters changes the etag, so buyers re-fetch; the header
  states filters may be added without a version bump.
- Affected data: existing listings are republished carrying explicit
  `capacity_backing: backed`. Without that step an exact filter would exclude them
  from backed queries and a permissive one would include them in unbacked queries.
  This is a registry concern and is separate from the site-side pool migration the
  prerequisite owns.
- Not affected: capacity admission, reservation, scheduling, fulfillment, or any
  provider path. An unbacked listing never reaches them.

## Dependencies and Related Changes

- **Depends on `pool-declared-advertisement-and-backing`.** Without a declaration
  that authorizes advertising a mode independently of proving delivery, an
  execution-less seller's pool authorizes no mode and nothing derived from it can
  advertise anything. That change also declares `capacity_backing` on the pool and
  guarantees a producer emits it for every pool, which is what makes this change's
  version-skew rule tractable rather than a guess.
- **Depends on `settle-listing-vocabulary`.** Landing the rename first is
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

- [x] `docs/development/ARCHITECTURE.md` — the "Storefront capacity boundary"
      subsection gains the declared-not-inferred rule and backing's independence
      from cardinality and settlement, promoted at this change's closeout when they
      become true. The Terms entries are promoted earlier, by
      `pool-declared-advertisement-and-backing`, since a pool declaring its backing
      is when the concept exists.
- [x] Existing subsystem specification —
      `openspec/specs/storefront-publication/spec.md` and
      `openspec/specs/registry-discovery/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

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
