# Tasks — unbacked listing publication

Depends on `settle-listing-vocabulary`,
`project-capacity-resources-without-hosts`, and
`pool-declared-advertisement-and-backing`. Do not begin Section 2 before all three have
landed.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`; a hand-built HTTP payload
does not satisfy the no-raw-calls rule.

## 0. Settled preconditions

Both decision gates are resolved; `design.md` carries the reasoning. These tasks
confirm the conclusions still hold against the code at implementation time rather
than re-deciding them.

- [ ] 0.1 Confirm `build_storefront_derivation_key` is reused unchanged, with the
      VM source envelope carrying the same fields it carries today and backing
      absent from it. Backing is fixed at pool creation, so a supply move is a move
      between pools and the key differs by `pool_id`; if pool-level backing
      immutability has not landed, stop — the unique index will block
      close-and-republish.
- [ ] 0.2 Confirm the completed binding trace still matches the code, in particular
      that no consumer has appeared needing both `PublicationBinding` and the
      narrowed backed form. One that does is a signal the separation is wrong, not
      a site to cast past.

## 1. Binding schema

- [ ] 1.1 Add an explicit backing discriminator column to
      `storefront_listing_bindings`, defaulting existing rows to capacity-backed.
- [ ] 1.2 Leave `site_id` `NOT NULL` and populated for every listing. It is the
      listing's origin site, which an unbacked listing has. Do not add a
      constraint tying the discriminator to `site_id` nullability, and do not make
      the column nullable: `StorefrontThreadBinding.site_id` is a non-empty string
      and the `negotiation_domain_binding_complete_insert` trigger is
      all-or-nothing across the six domain-binding columns, so a null site would
      make the listing unable to enter a negotiation at all.
- [ ] 1.3 Extend the existing immutability trigger to cover the discriminator, so
      a listing cannot change category after binding.
- [ ] 1.4 Confirm the migration is additive and that a database written by the
      previous version loads unchanged.

## 2. Admission provenance

- [ ] 2.1 Introduce `PublicationBinding` carrying `site_id`, `offering_mode`,
      `source_id`, and an `admission` discriminator over `Backed | Unbacked`.
      `CapacityBinding` becomes the narrowed backed form rather than staying
      unchanged — it is currently exactly the three common fields, so a marker
      beside it would carry no identity and the runtime's durable comparison would
      lose its token.
- [ ] 2.2 Widen `PublicationCandidate.binding` to `PublicationBinding` and keep
      the runtime's durable comparison a comparison of the whole binding,
      unchanged in behaviour.
- [ ] 2.3 Keep the publication runtime's durable-provenance comparison identical
      across both variants. The runtime uses provenance as an identity token, not
      to check availability, so this should be a type change rather than a branch;
      if a branch proves necessary, record why.
- [ ] 2.4 Confirm reserve, commit, release, schedule, and dispatch require the
      narrowed backed variant and refuse at the type boundary.
- [ ] 2.5 Relax the two identity-only `isinstance(..., CapacityBinding)` guards in
      the VM negotiation runtime — the one before settlement-artifact construction
      and the one on the negotiation opening, which leads into
      `require_capacity_binding`'s site-and-mode comparison. Left as they are they
      reject every unbacked listing at negotiation time. Keep the third, before the
      capacity hold, narrowing it to the backed form.
- [ ] 2.6 Widen the `PublicationDomainHooks.binding_for_listing` protocol return and
      move both implementing domains with it. This is a kit-boundary change, not a
      storefront-local one.
- [ ] 2.7 Update `apicredits`' `capacity_binding_from_offer` and
      `publication_service` for the new types. API credits are capacity-backed by a
      quota resource, so no behaviour changes — but the types and the protocol
      signature do, and omitting this domain would break its build.

## 3. Requirement scoping

- [ ] 3.1 Consume `pool-declared-advertisement-and-backing`: a listing derived from a
      pool may advertise only a mode that pool declares advertisable, backed or
      not. Do not read advertisement authorization out of `deliverable_modes` and
      do not make the pool conjunct vacuous — the first authorizes nothing for an
      execution-less seller, and the second would let a pool proving no VM
      delivery advertise VMs.
- [ ] 3.2 Leave offering-mode resolution from the frozen registration unchanged,
      and leave the `offer_resource.virtualization_type` equality requirement
      intact for every listing.
- [ ] 3.3 Scope the site-pinned claim-routing requirement to capacity-backed
      listings.
- [ ] 3.4 Scope capacity-availability reconciliation and close-before-reopen to
      capacity-backed listings.
- [ ] 3.5 Keep source-publication reconciliation applying to every listing: a
      removed or disabled source declaration closes its published listing, and a
      changed declaration is reflected deterministically. This is a separate loop
      from 3.4 and must not be scoped away with it.
- [ ] 3.5a Distinguish identity-bearing source changes from payload-only ones. The VM
      source envelope carries `site_id`, `pool_id`, `resource_id`, and `gpu_count`,
      and `derivation_key` hashes it, so changing a declared shape field in that
      envelope changes the key — and the binding is immutable, so it cannot be an
      in-place update. Identity-bearing changes close and republish; payload-only
      changes may update in place. Enumerate which published fields fall on each side
      before implementing, and record it.
- [ ] 3.6 Add the requirement that an unbacked listing has no source-inventory
      record on the storefront: no derived-listing row, no local resource table.
      This does not exempt it from source-publication reconciliation per 3.5.
- [ ] 3.7 Add a normative scenario for the backing transition: projected backing
      changes, the old listing closes, a new listing binds with a different
      durable identity and the new discriminator.
- [ ] 3.8 Scope `openspec/specs/site-capacity/spec.md`'s "Storefront
      capacity-claim identity" requirement. Its prose says a pool-only listing
      "produces a pool-scoped reservation claim" unconditionally; its four
      scenarios are already conditioned on a buyer reserving. Align the prose with
      the scenarios so the requirement describes claim construction when capacity
      admission is requested, rather than asserting every listing produces a
      claim.

## 4. Projection and publication

- [ ] 4.1 Read `capacity_backing` live from the current projection at each point of
      need, and do not cache the projected pool tag as storefront-local inventory.
      This is distinct from the durable backing discriminator on the listing binding,
      which is derived from it at publication and is immutable: the pool tag is a site
      fact the storefront reads, the discriminator is a storefront fact about a bound
      listing. Do not collapse the two — caching the tag makes the storefront an
      authority on a site fact, and re-deriving the discriminator per read lets a
      bound listing change category.
- [ ] 4.1a Implement the producer-version compatibility rules for both new pool
      tags. A projection whose producer emits a tag for no pool predates it:
      `capacity_backing` resolves to backed, and `deliverable_modes` serves as
      advertisement authorization. Log both, under rules with stated removal
      conditions. A projection carrying a tag for some pools and omitting it for one
      is a producer defect and that pool fails closed. Do not collapse these into
      one default — the second case is the never-infer rule.
- [ ] 4.1b Fail a pool closed when its `capacity_backing` value is outside `backed`
      and `unbacked`. A discriminator is not somewhere to apply the tolerant reading
      the cardinality hint gets.
- [ ] 4.3a Refuse a source declaration carrying no quantity where derivation needs
      one, rather than substituting the existing `int(... or 1)` default — a
      substituted 1 is indistinguishable in the published listing from a declared
      single-GPU shape. Do not add a published field describing how strong the
      shape claim is; every published field is a seller assertion on every listing,
      and backing already carries the exhaustibility difference.
- [ ] 4.4 Implement the backing transition as close-and-republish. When a source
      declaration's projected backing changes, the existing listing closes and a
      new listing binds with a new durable identity and the new discriminator.
      Do not let a generic source-reconciliation path attempt an in-place update:
      the discriminator is immutable, so an in-place attempt either aborts at the
      trigger or silently updates the public payload while leaving the durable
      category wrong. Because pool backing is fixed at creation, the transition
      arrives as a move between pools rather than as a changed value on one.
- [ ] 4.2 Derive unbacked candidates from the projection through the existing
      derivation path, using the `derivation_key` shape decided in 0.1.
- [ ] 4.3 Confirm no unbacked listing enters the capacity-availability
      reconciliation loop, and that every listing enters source-publication
      reconciliation.

## 5. Published shape and filter

- [ ] 5.1 Publish backing in `offer_resource`.
- [ ] 5.2 Republish existing listings carrying explicit `capacity_backing: backed` before
      adding the filter. They are semantically known to be backed and must not
      depend on an absent field to be classified.
- [ ] 5.3 Add an exact `on_missing: fail` backing filter to
      `core/registry/filter-spec.yaml`, matching the convention every other
      `offer_resource` filter uses. Permissive matching is wrong for a
      discriminator: a buyer asking for unbacked listings would otherwise receive
      every legacy backed listing that predates the field.
- [ ] 5.4 Confirm an unbacked listing validates against the existing `anyOf` on
      the strength of its settlement options, with no structural change to the
      listing shape.
- [ ] 5.5 Record the etag consequence: adding a filter changes the spec's etag and
      buyers re-fetch, without a version bump.

## 6. Validation

- [ ] 6.1 **Unit.** Binding schema constraint and immutability trigger over the
      discriminator; the admission-union type refusal; exhaustive filter-matching
      cases including a listing with no backing field under both backed and
      unbacked queries.
- [ ] 6.2 **Integration.** An unbacked listing publishes and then negotiates
      through the real storefront app, exercising the thread binding and the
      completeness trigger. This is the path the earlier null-site design would
      have broken, and only a real-DB test catches it.
- [ ] 6.3 **Integration.** An unbacked listing causes no reserve, site, or
      provider effect. Assert the capacity collaborator is *never invoked*, with
      the boundary mocked and verified uncalled — an effect-prevention claim a
      type-boundary unit test cannot make.
- [ ] 6.4 **Integration.** Publish and query backing through the canonical
      `RegistryClient` against the real registry app.
- [ ] 6.5 **Integration.** Removing or disabling a source declaration closes its
      published unbacked listing. This is the loop 3.5 keeps and nothing else covers.
- [ ] 6.5a **Integration.** A declared shape change that alters the derivation
      envelope closes the old listing and publishes a new one with a different
      derivation key, leaving the original binding row unmodified. A payload-only
      change, if any exist after 3.5a's enumeration, retains identity.
- [ ] 6.6 **Integration.** A backed listing's publication path is unchanged.
- [ ] 6.7 **System.** Backed and unbacked listings from one storefront are
      returned by one buyer query across running services.
- [ ] 6.8 **System.** Two seller sites publishing unbacked supply to one
      storefront retain distinct origin and source identity. Multi-site seller
      control is a stated reason for this design and nothing else proves it.
- [ ] 6.9 **Integration.** The real provisioning app emits `capacity_backing`, the
      canonical site client parses it, and the storefront consumes that exact
      response. This is a new interservice field and belongs in the
      client-to-API jurisdiction, not in a serializer unit test.
- [ ] 6.10 **Integration.** Old-producer skew for both tags: a projection emitting
      `capacity_backing` for no pool resolves every pool as backed; a projection
      emitting `advertisable_modes` for no pool authorizes advertisement from
      `deliverable_modes`, so a previously valid backed listing from an unupgraded
      site still publishes. Both log the compatibility rule. A projection emitting
      either tag for some pools and omitting it for one fails closed on that pool.
- [ ] 6.10a **Integration.** A projection carrying a `capacity_backing` value
      outside `backed` and `unbacked` fails that pool closed.
- [ ] 6.11 **System.** One representative mixed-version deployment covering both
      tags, if mixed site/storefront versions are supported. If they are not, record
      that decision rather than omitting the coverage silently.
- [ ] 6.12 **Integration.** Backing flip: supply moves from an unbacked pool to a
      backed one, the old listing closes, and a new listing binds with a different
      durable identity and derivation key. Assert the original binding row is
      unmodified — an in-place update that aborted at the trigger and one that
      succeeded look the same from the published side.
- [ ] 6.14 **Integration.** An unbacked listing reaches acceptance and
      settlement-artifact construction. This is what the two relaxed negotiation
      guards would otherwise break, and it fails loudly rather than subtly, so it is
      worth its own case rather than folding into 6.2.
- [ ] 6.15 **Unit.** A source declaration carrying no quantity is refused rather than
      published with a substituted default.
- [ ] 6.13 **Integration.** After 5.2, no listing in storefront-local state remains
      without an explicit backing value. Count, do not sample. Published registry
      copies are a separate concern: confirming those is rollout evidence across
      independently operated deployments, not a test this repository can own.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep at the binding is why origin and
      admission are separate, not which review found it.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the no-source-inventory rule
      and the two reconciliation loops landed as normative requirements, since
      both state behavior implementations must satisfy.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behavior, the 0.1 decision outcome, the accepted risks with their revisit
      triggers, and the open questions still unresolved.
- [ ] 7.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose. Goal 7 retains its rate-comparison gap, so the goal is
      not removed.
- [ ] 7.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`, including the completion
      dependency on `pools-9-retire-local-physical-authority` for the
      origination statement this change consumes and does not own.
- [ ] 7.7 **Promotion.** Promote the listing-level boundary statements to
      `docs/development/ARCHITECTURE.md` now that they are true, and complete the
      design-promotion record below. The Terms entries are not promoted here:
      `pool-declared-advertisement-and-backing` promotes those at its own closeout,
      because a pool declaring its backing is the point at which the concept becomes
      true. Confirm they landed there rather than promoting them twice.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Backing is declared, never inferred, and is independent of cardinality and settlement mechanism | `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary" |
| A listing's origin site is not its admission authority; the binding carries both separately | `openspec/specs/storefront-publication/spec.md` |
| Pool advertise-authorization is separate from execute-authorization | `openspec/specs/storefront-publication/spec.md` |
| Site-pinned routing and capacity-availability reconciliation are capacity-backed requirements; source-publication reconciliation applies to all listings | `openspec/specs/storefront-publication/spec.md` |
| An unbacked listing has no source-inventory record | `openspec/specs/storefront-publication/spec.md` |
| Backing transitions are close-and-republish, not in-place | `openspec/specs/storefront-publication/spec.md` |
| Identity-bearing source changes close and republish; payload-only changes may update in place | `openspec/specs/storefront-publication/spec.md` |
| Absent projected pool tags are producer-version compatibility rules, not per-pool inferences; a malformed backing value fails closed | `openspec/specs/storefront-publication/spec.md` |
| Claim construction describes what happens when capacity admission is requested | `openspec/specs/site-capacity/spec.md` |
| A published shape comes from its source declaration on every listing; a declaration with no quantity is refused rather than defaulted | `openspec/specs/storefront-publication/spec.md` |
| A listing advertises only a mode its pool declares advertisable, backed or not | `openspec/specs/storefront-publication/spec.md` |
| Backing is filtered exactly and fail-on-missing | `openspec/specs/registry-discovery/spec.md` |
