# Tasks — publish indicative listing rates

**Blocked.** Section 2 has no domain dependency and may proceed. Sections 3–4 wait
on `bare-metal-listing-shapes`, because bare metal is Goal 7's primary target domain
and cannot read an asking rate until it publishes a capability shape per listing;
`bare-metal-publication-reads-pool-declarations`, which made its publication read
pool declarations, is complete. The unbacked-supply system validations (7.11–7.13)
additionally wait on `unbacked-bare-metal-listings` for bare metal and
`compose-contact-exchange-across-compute` for VM.

This task list is a baseline carried from the design phase. It is rewritten during
planning, which names the exact files each accepted decision touches.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Settled decisions to confirm against code

No decision gate remains open except 4.0. The tasks below confirm the code facts
each decision rests on still hold, and stop rather than proceed if one has moved.

- [ ] 1.1 Confirm `market_alkahest.schemas.PER_UNIT_SECONDS` still holds exactly
      `{"hour": 3600}`. The hourly-only rule is a local asking-rate contract
      validated against that table for parity, not a rule inherited from it.
- [ ] 1.2 Confirm `SettlementPublicationClause` still expresses a published rate as
      an opaque `asset` string and positive decimal `rate` text without an exponent,
      with rate and unit required together.
- [ ] 1.3 Confirm the settlement clause grammar still restricts `asset` to equality
      operators.
- [ ] 1.4 Confirm `contact-exchange.v1` options remain rateless; if that mechanism
      gains a rate, revisit the carrier decision before implementing.
- [ ] 1.5 Confirm the site-scoped pool-override store still applies to a pool at any
      configured site and replaces shapes and settlement clauses as whole lists, and
      that `listing_comparison` still refreshes term fields in place. The override
      precedence and the in-place lifecycle rest on both.
- [ ] 1.6 Confirm the registry still validates its full `listing_shape` only in the
      dry run. If publish-boundary enforcement has been added, the refusal of a
      partial rate may also move there; re-read `design.md` before relying on it.

## 2. Generic registry prerequisite

The engine cannot evaluate this change's field as it stands. Section 4 is blocked on
this section. Nothing in this section may name a rate, an asset, a period, or any
compute field.

- [ ] 2.1 Add an exact-decimal declared value type to the filter specification
      vocabulary — wire and stored representation a decimal-text string, comparison
      domain exact decimal. Extend `ValueType`, add the coercion branch, widen
      `_Range`'s bound domain, and accept decimal-text resolved values in range
      evaluation.
- [ ] 2.1a Leave the existing `number` type's behaviour unchanged.
- [ ] 2.1b Add the buyer-side mapping entry to `QueryValueType.DECIMAL`. No
      rendering change is needed.
- [ ] 2.1c Preserve a registry refusing to load a spec declaring a value type it
      does not implement.
- [ ] 2.2 Add a `requires` list to `FilterDecl` naming other declared filters that
      must accompany it, and refuse a query supplying a filter without them. Make the
      dependency one-directional.
- [ ] 2.2a Read `requires` from the specification in both the registry and the buyer
      query compiler, mapping filter names to query names on the buyer side. Encode no
      specific field's dependency in code.
- [ ] 2.2b Follow the shape `strict.<n>` already establishes: a cross-cutting query
      concern resolved before the criterion loop, whose target is validated against
      the declared filter set.
- [ ] 2.2c Reject at spec-validation time a `requires` entry naming an undeclared
      filter, naming its own declaration, or participating in a cycle.
- [ ] 2.2d Serialize a declaration with no co-requirement exactly as today, in the
      served specification and in the etag input, and pin it with a test against a
      literal digest. The existing schema-identity precedent test builds its expected
      payload from the model's own dump and would not detect a new defaulted field.

## 3. Declaration, resolution, and publication

- [ ] 3.1 Add the domain-neutral `asking_rates` policy tag: a mapping of offering mode
      to a list of `{shape, amount, asset, period}` entries, with the structural check
      applied identically at every pool-write surface and a raw reader beside the
      `listing_shapes` reader.
- [ ] 3.2 Add the asking-rate value contract shared by VM and bare metal: decimal-text
      amount, opaque trimmed asset, and a period this version accepts (`hour`),
      validated against `PER_UNIT_SECONDS` for parity while the rule stays local.
- [ ] 3.3 Add asking rates to the site-scoped pool-override store beside listing
      shapes, validated by the market for its shape vocabulary, replacing the pool's
      list as a whole and accepting an empty list as withholding every rate.
- [ ] 3.4 Resolve each listing's rate by canonical shape digest through the override,
      then the pool declaration, then none. Supply no rate from storefront
      configuration. Report entries naming an unpublished shape.
- [ ] 3.5 Hold a pool whose declaration or override is unreadable — unknown shape
      vocabulary, a duplicate shape, or an invalid amount, asset, or period — and
      report it. Do not fall through; `design.md` records why this diverges from
      `_VALID_HINT_FIELD` and the divergence must not be "fixed" later.
- [ ] 3.6 Publish `listing_resource.asking_rate` for VM listings, excluded from every
      shape digest and derivation identity.
- [ ] 3.7 Treat the asking rate as a term of sale in listing comparison, so a change
      or removal refreshes the listing in place.
- [ ] 3.8 Publish and refresh the asking rate for bare-metal listings through the same
      resolution, once bare-metal publication reads pool declarations and publishes a
      capability shape per listing.
- [ ] 3.9 Do not populate the asking rate from a mechanism rate, and do not write it
      into a settlement carrier. Confirm a listing carrying both publishes without
      either being reconciled against the other.

## 3b. Bare metal joins the site-scoped override store

Baseline from `bare-metal-listing-shapes`' design review, which moved this work here;
see "Bare metal joins the site-scoped override store" in `design.md`. Rewritten with
exact files at planning.

- [ ] 3b.1 `kit/pool-overrides`:
      - add the framework-free `PoolOverrideRouteService` (`replace`, `read`,
        `delete`);
      - make `refresh_site` and `wake_publication` optional;
      - bump the version;
      - add unit tests over a service double, and integration tests against the real
        store, including a storefront with no cache and no loop.
- [ ] 3b.2 VM storefront: reduce the three override handlers in `admin_controller.py`
      to bindings over the route service. VM's existing override integration,
      identity-dispatch, client-parity, and CLI tests must pass unchanged.
- [ ] 3b.3 Bare-metal storefront:
      - the `bare_metal` contribution and its terms model;
      - the kit's override migration and the accepted-generation table;
      - every publication run records each accepted generation;
      - override status in system status;
      - three admin routes bound through `_admin`;
      - clause and duration precedence in `publication_composition.py`, holding a
        pool whose override is unreadable.
- [ ] 3b.4 Bare-metal `pool-override` command over the kit's typed client, as recorded
      in `design.md`.
- [ ] 3b.5 Integration through the typed clients:
      - replace, read, list, and delete;
      - refusals of shapes, unknown terms, an unconfigured site, an unreachable
        site, and an unknown pool;
      - status `unknown` before any run, `applied` after a run from the command,
        `orphaned`, and `site_unconfigured`;
      - an override's clauses and durations reaching a refreshed listing.
      A VM storefront test shows the combined shell still refuses a `bare_metal`
      write.
- [ ] 3b.6 End-to-end: the bare-metal publication scenario writes an override through
      the kit client, steps publication, and observes the refreshed term at the
      registry.

## 4. Filters and the compute schema

Blocked on Section 2.

- [ ] 4.0 **Decision gate.** Decide the buyer-facing `query_name`s for the two bound
      filters (see `design.md`, "Open questions") and record the decision and its
      reasoning in `design.md` before 4.1.
- [ ] 4.1 Declare `asking_rate_max`, `asking_rate_min`, `asking_rate_asset`, and
      `asking_rate_period` in `core/registry/filter-spec.yaml` with the paths, ops,
      types, and alias kinds `design.md` fixes and the query names 4.0 decides.
- [ ] 4.1a Make all four `on_missing: fail`.
- [ ] 4.1b Declare `requires: [asking_rate_asset, asking_rate_period]` on both bound
      filters.
- [ ] 4.1c Match only listings quoting the named period and asset; convert across
      neither.
- [ ] 4.2 Declare the `asking_rate` object in the compute `listing_shape`, all three
      fields required when present, so the dry run and the served self-description
      describe it.
- [ ] 4.3 Record the etag consequence: the compute specification's etag changes and
      buyers re-fetch, without a version bump; no other specification's etag changes.

## 5. Specification

- [ ] 5.1 State the two engine capabilities in
      `openspec/specs/registry-discovery/spec.md`, including that an undeclared
      co-requirement leaves a specification's serialization and etag unchanged.
- [ ] 5.2 State the compute schema's asking-rate field and its filters there, and that
      the registry validates the field only in the dry run.
- [ ] 5.3 State in `openspec/specs/storefront-publication/spec.md` the per-shape
      declaration and precedence, the absence of a configuration default, the
      fail-closed rule, the listing-attribute and independent-carrier rules, and the
      in-place refresh.
- [ ] 5.4 State the `asking_rates` policy tag and its structural validation in
      `openspec/specs/resource-pool-management/spec.md`.
- [ ] 5.5 Record in `openspec/specs/storefront-publication/architecture.md` why the
      rate is keyed by shape beside the shape, why the storefront has final authority
      with no configuration default, and why a site-declared range is deferred.

## 6. Cross-change reconciliation

- [x] 6.1 Amend `capacity-shape-pricing` so its single-rate compatibility reading
      names the negotiation-side rate and cannot be read as reinterpreting a published
      asking rate. Already present in that change's design.
- [x] 6.2 Correct `docs/development/ROADMAP.md`'s Goal 7 claim that no compute listing
      publishes a price. Current-state text and the gap row now say the price exists
      only inside settlement carriers and no filter reads it.
- [x] 6.3 Correct this change's row in `openspec/changes/README.md` and record it as
      blocked on the bare-metal changes.

## 7. Validation

- [ ] 7.1 **Unit.** Exact-decimal comparator behaviour: bounds at, above, and below a
      value; inclusive against exclusive at equality; a value with more significant
      digits than a double holds; a resolved listing value of the wrong shape.
- [ ] 7.2 **Unit.** Co-requirement declaration validation: unknown target,
      self-reference, cycle, one-directional supply, criterion construction for a
      satisfied co-requirement, and serialization unchanged when undeclared.
- [ ] 7.3 **Unit.** Asking-rate value contract and resolution: missing field, boundary
      amounts, an unsupported period, a duplicate shape, shape matching by digest,
      override replacement and the empty override list, and — with a synthetic second
      period — a cross-period query excluding rather than converting.
- [ ] 7.4 **Integration.** Exact decimal round-trip through the canonical
      `RegistryClient` against the real registry app, matching or excluding on the
      true value.
- [ ] 7.5 **Integration.** A valid three-part rate query through the canonical
      `RegistryClient`; and a narrow raw-ASGI rejection-path request supplying an
      amount bound without its asset, proving the registry itself refuses.
- [ ] 7.6 **Integration.** Pool write surfaces refuse a structurally malformed
      `asking_rates` identically on create, replace, patch, and bulk import, and project
      a valid one verbatim.
- [ ] 7.7 **Integration.** Seller authoring through the real pool administration client
      and projection: a rate declared for each of two shapes reaches each shape's
      publication candidate and then the registry.
- [ ] 7.8 **Integration.** Override authority: an override for a pool at a non-first
      site replaces the declared rate; an empty override list withholds every rate; a
      storefront with pricing defaults and no declaration publishes no rate.
- [ ] 7.9 **Integration.** Rate lifecycle: change amount, asset, and period and confirm
      each listing refreshes in place under its identity; remove the entry and confirm
      the listing stays discoverable but absent from rate-bounded queries.
- [ ] 7.10 **Integration.** An unreadable declaration or override holds its pool rather
      than publishing a fallback or a rateless listing.
- [ ] 7.11 **Integration.** No settlement option, escrow term, or accepted obligation
      carries a value derived from the published rate, and a published rate is not
      populated from a mechanism rate. Exercise through the real storefront composition.
- [ ] 7.12 **Integration.** A listing advertising a rateless option publishes an asking
      rate and is returned by a rate-bounded query while its option remains rateless.
- [ ] 7.13 **System.** A buyer query bounded by rate returns backed and unbacked
      listings together, bare metal and VM, and excludes listings publishing no rate.
      Blocked on `unbacked-bare-metal-listings` and
      `compose-contact-exchange-across-compute`.
- [ ] 7.14 **System.** Multi-seller provenance: one storefront publishing for two seller
      sites, each site's declared rates reaching only its own listings, and an override
      for one site leaving the other's rates unchanged.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why nothing is constructed from the rate,
      why the asking rate is not derived from a mechanism rate, why the rate is excluded
      from shape identity, and why a malformed declaration fails closed against the
      resolver's fall-through convention.
- [ ] 8.2 **Import placement.** Review imports this change added or touched and migrate
      function-level ones to module level where no genuine circular import or documented
      lazy-load reason exists. Verify against the real test suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the engine capabilities landed in
      `registry-discovery`, the publication rules in `storefront-publication`, and the
      policy tag in `resource-pool-management`.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      material validation evidence, deferred work, and permanent-documentation
      destinations.
- [ ] 8.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md`. If this closes Goal 7's last gap, remove the goal and
      absorb its result into permanent documentation — check the remaining rows first.
- [ ] 8.6 **Campaign index currency.** Update this change's row and Goal 7's dependency
      graph in `openspec/changes/README.md`.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=publish-indicative-listing-rates` and resolve every
      match.
- [ ] 8.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record the
      evidence: the run, its result, and the scenarios that exercise this change's
      behaviour. If the pipeline cannot run for a reason unrelated to this change, record
      that as an explicit blocker naming the cause and the change that owns it, and treat
      the validations it gates as unrun rather than passed.
- [ ] 8.9 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An exact-decimal declared value type whose comparison never passes through binary floating point | `openspec/specs/registry-discovery/spec.md` |
| Declarative filter co-requirements, resolved from the specification by registry and buyer alike | `openspec/specs/registry-discovery/spec.md` |
| An undeclared co-requirement leaves a specification's serialization and etag unchanged | `openspec/specs/registry-discovery/spec.md` |
| The compute schema's asking-rate field, validated by the registry only in the dry run | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period and the asset rather than normalizing across them; a listing publishing no rate is excluded | `openspec/specs/registry-discovery/spec.md` |
| The asking rate is declared per shape; override, then pool declaration, then none; no configuration default | `openspec/specs/storefront-publication/spec.md` |
| A malformed asking-rate declaration holds its pool | `openspec/specs/storefront-publication/spec.md` |
| The asking rate is a listing attribute and independent of any mechanism rate | `openspec/specs/storefront-publication/spec.md` |
| An asking-rate change refreshes the listing in place | `openspec/specs/storefront-publication/spec.md` |
| The `asking_rates` policy tag and its structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Why the rate is keyed by shape, why the storefront has final authority, why a site range is deferred | `openspec/specs/storefront-publication/architecture.md` |
| Goal 7 current state and gap ownership | `docs/development/ROADMAP.md` |
