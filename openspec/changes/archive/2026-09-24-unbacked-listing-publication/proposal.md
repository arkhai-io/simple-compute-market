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
- Let an unbacked listing publish only settlement options its domain does not fulfil
  through capacity. The domain's settlement composition declares this per composed
  mechanism; an unbacked candidate drops the rest with an operator notice and yields no
  listing if none remains, so no ordinary deal on an unbacked listing is funded and then
  refused at fulfillment.
- Run publication as a storefront lifecycle loop: derive, publish, refresh, close, hold,
  and reopen in-process on a timer and on projection change, held by the storefront's
  existing lifecycle pause and stepped by `run-cycle` and `dry-run` controls.
  `market-storefront publish` becomes a typed-client front end for those controls and
  stops reading the database or publishing to its own storefront by HTTP.
- Take terms only from durable sources: retire the `--settlement` and
  `--max-duration-seconds` command arguments, which replaced the configured default
  tiers for one process and cannot be reproduced by reconciliation.
- Record who closed a listing, seller or reconciliation, so no reconciliation path
  reopens or replaces a listing its seller withdrew.
- Read a projected pool's `enabled` declaration, so a disabled pool's listings close.
- Publish `capacity_backing: backed` on bare-metal listings, and apply the listing
  identity rule to bare metal through its own publication source.

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
- Do not publish backing on API-credit listings or add a backing filter to the
  API-credits registry schema. They are a separate schema identity and always
  quota-backed.
- Do not make bare-metal publication autonomous. Its image does not publish on its own
  today and is not release-qualified.
- Do not add a storefront settings API. Storefront-wide terms stay in configuration.
- Do not compose contact exchange for VM here. `compose-contact-exchange-across-compute`
  owns that; this change's system evidence waits on it.

## Impact

- Affected code: `core/storefront`'s binding schema, listings table, migrations,
  binding repository, and publication runner; `core/storefront-client`'s lifecycle
  client docstrings; `kit/capacity-publication`'s binding types, publication runtime,
  and the `PublicationDomainHooks` protocol; `kit/negotiation-runtime`'s
  `RoundRequest`; the storefront-side projection ingestion, system status, lifecycle
  loops and admin controls; the VM negotiation runtime's binding guards; the VM seller
  inventory guard in `domains/vms/negotiation`; the VM reconciler in
  `domains/vms/listings`; the VM storefront's publication source, publication service,
  settlement composition, listing service, and `publish` command; the legacy
  storefront-domain migration tool; the bare-metal listing model, publication source,
  and binding writers; and the API-credit domain's binding types and close path.
  API-credit behaviour does not change — it is capacity-backed by a quota resource —
  but its types move with the protocol.
- Affected behaviour for existing backed listings: open listings begin reflecting
  term changes, a published identity field that diverges from its source closes its
  listing, the inventory guard checks each listing against its own source rather than
  any matching row anywhere, a seller's close is no longer undone by the next capacity
  event, and a disabled pool's listings close. Each is a correction of stale or
  unscoped behaviour.
- Affected operator workflow: the storefront publishes every derivable slice of every
  advertisable pool without a command; `market-storefront publish` triggers or previews
  a cycle rather than running one; and storefront-wide settlement clauses change by
  configuration rather than by command argument.
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
  provider path. An unbacked listing never reaches them: it publishes no settlement
  option its domain fulfils through capacity, and the binding types refuse it at the
  capacity boundary behind that.

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
- **System evidence depends on `compose-contact-exchange-across-compute`.** An unbacked
  VM listing publishes only options its domain does not fulfil through capacity, and
  until contact exchange is composed for VM no such option exists. Tasks 6.7 and 6.8 and
  the end-to-end closeout therefore wait on that change's Sections 1–3 and 3b, which wait
  on `contact-payload-retention`. Implementation does not.
- **Related, not blocking:** `pools-8-capacity-projection-and-listing-hints` receives
  the confirmed region-at-admission finding, and
  `pools-9-retire-local-physical-authority` is told that `publish --inventory` is
  retired here and that the per-pool override write path remains its own.
- **`pools-9-retire-local-physical-authority` widens what this change promoted.**
  This change's origination rule is promoted scoped to unbacked listings, which it
  makes true; retiring the local-table path makes it true of every listing, and
  that change's promotion widens it. First recorded as a completion dependency;
  discharged at closeout (`design.md`, "Closeout: system evidence and completion").
- **System evidence belongs to `compose-contact-exchange-across-compute`.** Tasks
  6.7 and 6.8 moved there as its 6.4 and 6.5.

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
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the binding-schema and
      closure-reason rollback posture.
- [x] `docs/development/TESTING.md` — the storefront's lifecycle loops, including
      publication, in the pause-and-step table.
- [x] `docs/seller-quickstart.md` — publication without `--settlement` or
      `--inventory`, and the loop controls.
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
- The binding discriminator and the closure reason are enforced by trigger, and
  rollback past this change drops those triggers —
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Combined compute-family storefront".
- An unbacked listing publishes only settlement options its domain does not fulfil
  through capacity — `openspec/specs/storefront-publication/spec.md`.
- Publication runs as a controllable storefront lifecycle loop —
  `openspec/specs/storefront-publication/spec.md`; the loop's controls in
  `docs/development/TESTING.md`.
- Terms come only from durable sources — `openspec/specs/storefront-publication/spec.md`.
- A seller's close is durable and no reconciliation path undoes it —
  `openspec/specs/storefront-publication/spec.md`.
- Bare-metal listings publish backing — `openspec/specs/registry-discovery/spec.md`.
