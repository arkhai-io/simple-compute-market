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
  pool tag, judged jointly per site and per projection generation. A generation in
  which no pool carries either tag comes from a producer that predates them: every
  pool reads as backed and `deliverable_modes` serves as advertisement
  authorization, reproducing the old contract under one logged compatibility rule
  reported in the storefront's system status. In any other generation a pool whose
  declarations are absent, malformed, or inconsistent is unresolvable: it yields no
  new candidates and its existing listings are held — neither closed nor refreshed —
  until it resolves.
- Implement a backing transition as close-and-republish rather than an in-place
  update, since the durable discriminator is immutable.
- Scope the site-pinned claim-routing requirements, capacity-availability
  reconciliation, and close-before-reopen to capacity-backed listings. The scoping is
  made in the slice builder: an unbacked pool's slices range over its declared
  quantity, a backed pool's over its available quantity.
- Keep source-publication reconciliation for every listing, and make it complete: the
  publication cycle refreshes terms of sale on open listings in place, which no
  listing receives today, and finds closed listings by derivation key in the common
  binding.
- Define listing identity: a listing's identity is the physical resource it offers,
  and everything else is a term of sale. A listing commits only to the fields it
  publishes. A term changes in place; a change to the resource is a different
  listing. Where the current key does not capture a changed identity field, the
  listing closes and reopening is refused while the difference persists; completing
  the key is recorded as an open question in `publish-multidimensional-listing-shape`.
- Make the seller's inventory guard check each listing against its own source: every
  published field sourced from the declaration or pool is rechecked against that
  source for every listing, and availability is checked for backed listings only.
  `kit/negotiation-runtime` forwards the durable binding on its round carrier so the
  guard can.
- Finish retiring `derived_compute_listings` on the publication path: publication,
  close, and reopen neither read nor write it.
- Publish backing in `listing_resource` and add an exact, fail-on-missing registry
  filter for it, republishing existing listings as explicitly backed so no listing
  relies on an absent field to be classified.
- Make derivation strict about the enumeration quantity: a declaration without
  `gpu_count` yields no listing and an operator notice, a declared zero yields no
  listing silently, and a malformed count leaves the member unresolvable. No
  derivation path substitutes a default. Publish no second field describing how
  strong a listing's shape claim is: every published field is a seller assertion on
  every listing, and the exhaustibility difference is already carried by the
  published backing value.
- Add the binding discriminator in two migrations — an expand that adds a nullable
  column, backfills every existing row as backed, and extends the immutability
  trigger, then a contract that refuses an insert naming no backing — so no writer
  can omit the category and none is classified by a column default.

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
- Do not migrate a listing automatically when a physical-resource field the current
  key does not capture changes, and do not fix mixed-kind fungible pools. Both follow
  from completing the listing key, which `publish-multidimensional-listing-shape`
  owns as an open question; this change closes and holds such listings, and logs a
  warning for mixed-kind pools.
- Do not add site-side validation refusing mixed-kind pools.

## Impact

- Affected code: `core/storefront`'s binding schema, migrations, binding repository,
  and publication runner; `kit/capacity-publication`'s provenance types, publication
  runtime, and the `PublicationDomainHooks` protocol; `kit/negotiation-runtime`'s
  `RoundRequest`; the storefront-side projection ingestion and system status; the VM
  negotiation runtime's binding guards; the VM seller inventory guard in
  `domains/vms/negotiation`; the VM reconciler and publication cycle in
  `domains/vms/listings` and the VM storefront; the legacy storefront-domain
  migration tool; and both the VM and API-credit domains' publication candidate
  derivation and capacity clients. API-credit behaviour does not change — it is
  capacity-backed by a quota resource — but its types move with the protocol.
- Affected behaviour for existing backed listings: open listings begin reflecting
  term changes, a published identity field that diverges from its source closes its
  listing, and the inventory guard checks each listing against its own source rather
  than any matching row anywhere. Each is a correction of stale or unscoped behaviour.
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
- **Related, not blocking:** `publish-multidimensional-listing-shape` carries the
  listing-identity open question this change's interim behaviour stands in for, and
  its dimensions extend the inventory guard's coverage without a guard change.
  `capacity-shape-pricing`'s guard task narrows to buyer-requested shapes.
  `capacity-shape-envelope` and `negotiation-capacity-feasibility-probe` sit beside
  the guard as admissibility and authoritative availability.
  `add-harness-scenario-contract` learns the guard's new declared-match reason.
  `multi-domain-storefront-composition` receives a correction note on its
  binding-lookup task, whose remaining legacy-table reads and writes this change
  removes.
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
      `openspec/specs/storefront-publication/spec.md`,
      `openspec/specs/site-capacity/spec.md`, and
      `openspec/specs/registry-discovery/spec.md`; companion
      `openspec/specs/storefront-publication/architecture.md` for the listing-identity
      rationale.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the binding-schema rollback
      posture.
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
- A listing's identity is the physical resource it offers; terms of sale change in
  place; a listing commits only to the fields it publishes —
  `openspec/specs/storefront-publication/spec.md`, with rationale in its companion
  `architecture.md`.
- The seller's inventory guard rechecks every published source-derived field against
  the listing's own source, and checks availability only for backed listings —
  `openspec/specs/storefront-publication/spec.md`.
- Projected pool declarations are judged jointly per site generation; unresolvable
  pools are held — `openspec/specs/storefront-publication/spec.md`.
- The common listing binding is the only VM listing mapping —
  `openspec/specs/storefront-publication/spec.md`.
- The binding discriminator is enforced by trigger, and rollback past this change
  drops the required-insert trigger — `docs/development/DEPLOYMENT_AND_CONFIG.md`,
  "Combined compute-family storefront".
