# Tasks — publish indicative listing rates

Depends on `unbacked-listing-publication`. Do not begin Section 3 before it has
landed.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Settled decisions to confirm against code

No decision gate remains open. The tasks below confirm the code facts each
decision rests on still hold, and stop rather than proceed if one has moved.

- [ ] 1.1 Confirm `PER_UNIT_SECONDS` still holds exactly `{"hour": 3600}`. The
      hourly-only rule is a local asking-rate contract validated against that table
      for parity, not a rule inherited from it — a second entry appearing there
      does not automatically widen publication.
- [ ] 1.2 Confirm `SettlementPublicationClause` still expresses a published rate as
      an opaque `asset` string and positive decimal `rate` text without an exponent,
      with rate and unit required together. The asking rate reuses that vocabulary
      rather than stating a second one.
- [ ] 1.3 Confirm the settlement clause grammar still restricts `asset` to equality
      operators. The exclude-rather-than-convert rule for assets depends on no
      surface ordering or converting them.
- [ ] 1.4 Confirm `contact-exchange.v1` options remain rateless. A listing whose
      only mechanism declines scalar participation is the case that makes a separate
      listing-level field necessary rather than a filter over the settlement
      carrier; if that mechanism gains a rate, revisit the carrier decision before
      implementing.
- [ ] 1.5 Confirm `_local_pool_pricing` still scopes the storefront's per-pool
      commercial table to `home_site` only. The no-default-off-site rule relies on
      that tier already being structurally unavailable for a remote origin's pool.

## 2. Generic registry prerequisite

The engine cannot evaluate this change's field as it stands, and neither gap is
fixable by adding filter-spec entries. Section 4 is blocked on this section.

- [ ] 2.1 Add an exact-decimal declared value type to the filter specification
      vocabulary — wire and stored representation a decimal-text string, comparison
      domain exact decimal. Extend `ValueType`, add the coercion branch, widen
      `_Range`'s bound domain, and accept decimal-text resolved values in range
      evaluation. Today `_Range.min`/`max` are `float | int`, `number` coerces with
      `float(raw)`, and range evaluation filters resolved values through
      `isinstance(v, (int, float))`, so a decimal-text listing value matches no
      range at all.
- [ ] 2.1a Leave the existing `number` type's behaviour unchanged. It is declared on
      `sla` today and on every JSON-number field another deployment's spec declares;
      retyping its comparison domain would silently change their semantics.
- [ ] 2.1b Add the buyer-side mapping entry to `QueryValueType.DECIMAL`. No
      rendering change is needed: `_scalar` already emits
      `format(value.normalize(), "f")` with no binary-float conversion, so the
      client is already exact end to end.
- [ ] 2.1c Confirm a registry refuses to load a spec declaring a value type it does
      not implement rather than ignoring it. `FilterDecl` forbids extras and
      `ValueType` is a closed `Literal`, so this is current behaviour to preserve
      and the reason the engine must ship before any spec that uses the new type.
- [ ] 2.2 Add a `requires` list to `FilterDecl` naming other declared filters that
      must accompany it, and refuse a query supplying a filter without them. Make
      the dependency one-directional: a co-required filter supplied alone stays a
      valid constraint.
- [ ] 2.2a Read `requires` from the specification in both the registry and the
      buyer query compiler. Do not encode any specific field's dependency in code —
      `registry-discovery` requires the compiler to resolve every rule from the
      active specification and add no domain fields, so a conditional naming
      `asking_rate` would violate a normative requirement rather than merely being
      inelegant.
- [ ] 2.2b Follow the shape `strict.<name>` already establishes: a cross-cutting
      query concern resolved before the criterion loop, whose target is validated
      against the declared filter set.
- [ ] 2.2c Reject at spec-validation time a `requires` entry naming an undeclared
      filter, naming its own declaration, or participating in a cycle.

## 3. Published shape and seller authoring

- [ ] 3.1 Publish one `asking_rate` object on the listing resource carrying
      `amount`, `asset`, and `period`. Freeze the shape as `design.md` records it —
      a sibling of the flattened dimension fields, not nested under a capability
      family. `publish-multidimensional-listing-shape` keeps the flattened
      convention inside the listing resource, and a listing-wide price belongs to no
      family.
- [ ] 3.1a Carry `amount` as exact decimal text, `asset` as an opaque non-empty
      identifier requiring no contract address, decimals, or chain identity, and
      `period` as `hour`. Validate the period against `PER_UNIT_SECONDS` for parity
      while keeping the normative rule local to the asking rate.
- [ ] 3.1b Refuse publication of a rate missing its amount, asset, or period.
- [ ] 3.2 Read the rate from a declaration on the origin site's Resource Pool,
      carried in the projected domain-owned `pricing` policy tag as a sibling of the
      per-model structure rather than a member of it. No `resource-pool-management`
      change follows: that capability already declares `pricing` domain-neutral and
      opaque with unknown tags forward-compatible.
- [ ] 3.2a Allow the storefront's per-pool override and `[pricing]` config default
      to resolve an asking rate **only** for `home_site` pools. Never apply either
      to a pool at another origin — a storefront-wide default reaching a remote
      seller's listing advertises the aggregator's price as that seller's.
- [ ] 3.2b Publish no asking rate where a pool declares none and no default
      applies. The listing publishes normally and is absent from rate-bounded
      discovery.
- [ ] 3.2c Fail a pool closed on a malformed or partial asking-rate declaration
      rather than falling through. This diverges from `_VALID_HINT_FIELD`'s
      treat-as-absent convention deliberately; `design.md` records why, and the
      divergence should not be "fixed" toward fall-through later.
- [ ] 3.3 Publish it for backed and unbacked listings alike. Confining it to
      unbacked listings would make its presence a second encoding of backing.
- [ ] 3.4 Do not populate the asking rate from a mechanism rate, and do not write a
      published asking rate into a settlement carrier. Both directions are refused.
- [ ] 3.5 Confirm a listing carrying both an asking rate and a mechanism rate
      publishes without either being reconciled against the other, and that a
      disagreement between them is not a publication error.
- [ ] 3.6 Republish in place on a rate change: an amount, asset, or period change
      republishes derived listings under their existing durable identity, and a
      removal republishes them without a rate. Route it through source-publication
      reconciliation, not capacity reconciliation. Only a backing change closes and
      republishes under a new identity.

## 4. Filters

Blocked on Section 2. Adding these declarations to a spec served by an engine
without the new primitives fails spec loading.

- [ ] 4.1 Declare `asking_rate_max`, `asking_rate_min`, `asking_rate_asset`, and
      `asking_rate_period` in `core/registry/filter-spec.yaml` with the exact paths,
      ops, types, and alias kinds `design.md` fixes. This change lands after
      `settle-listing-vocabulary`, so the paths are `listing_resource`.
- [ ] 4.1a Make all four `on_missing: fail`, matching every other published-shape
      filter and its stated reason.
- [ ] 4.1b Declare `requires: [asking_rate_asset, asking_rate_period]` on both
      bound filters, so the co-requirement lives in the specification.
- [ ] 4.1c Match only listings quoting the named period; do not convert across
      periods. With one accepted period this has no observable effect today; it is
      implemented now so accepting a second does not silently turn every hourly
      query into a cross-period comparison.
- [ ] 4.1d Match assets by equality only; do not convert across them. Conversion
      needs an external exchange rate that moves continuously and would make the
      registry an authority on relative asset value.
- [ ] 4.2 Confirm a listing publishing no rate is excluded from a rate-bounded
      query rather than passing it.
- [ ] 4.3 Record the etag consequence: adding filters changes the spec's etag and
      buyers re-fetch, without a version bump.

## 5. Specification

- [ ] 5.1 State the two engine capabilities in
      `openspec/specs/registry-discovery/spec.md`: an exact-decimal declared value
      type whose comparison never passes through binary floating point and which
      leaves the JSON-number type unchanged, and declarative filter
      co-requirements resolved from the specification by both the registry and the
      buyer compiler.
- [ ] 5.2 State the asking rate's frozen shape there — `amount` as decimal text,
      opaque `asset`, `period` as the supported time-rate unit, all three required
      together, one per listing, never decomposed or nested under a family.
- [ ] 5.3 State that the published rate is a listing attribute and not a settlement
      option rate: nothing is constructed from it and an agreed amount is absent
      until negotiated. Write it as a statement about what the system builds, not
      about how strong the claim is — every published field is a seller assertion
      and the spec must not imply otherwise.
- [ ] 5.4 State that the asking rate and a mechanism rate are independent carriers:
      not required to agree, neither correcting the other, neither derived from the
      other.
- [ ] 5.5 State in `openspec/specs/storefront-publication/spec.md` that the asking
      rate is declared at the listing's origin pool, that storefront override and
      default apply to `home_site` pools only, that a malformed declaration fails
      its pool closed, that the rate is never derived from or written into a
      settlement carrier, and that a rate change republishes in place. This is
      publication provenance rather than registry behaviour and does not belong in
      `registry-discovery`.
- [ ] 5.6 Add scenarios for: a rate-bounded query against a listing publishing no
      rate; no settlement option, escrow term, or obligation carrying a derived
      value; a rate quoted in an asset with no contract address, decimals, or chain
      identity; a rate bound refused for a missing asset or period; and an exact
      comparison at a precision a double cannot hold.

## 6. Cross-change reconciliation

- [ ] 6.1 Amend `capacity-shape-pricing`'s design and its `storefront-publication`
      delta so its single-rate compatibility reading names the negotiation-side rate
      explicitly and cannot be read as reinterpreting a published asking rate as a
      primary-dimension rate. The two are distinct quantities: a catalogue price and
      a negotiation rate structure. A storefront may derive the former from the
      latter where seller policy says so; the structure never subsumes it.
- [ ] 6.2 Correct `docs/development/ROADMAP.md`'s Goal 7 current-state claim that
      "no compute listing publishes a price at all". A seller price is published
      today inside the escrow and settlement-option rate carriers; what is missing
      is a listing-level asking rate and any filter over a rate value. This is
      permanent current-state documentation and the sentence is false today
      independent of whether this change lands, so correct it in the design branch
      rather than at closeout.
- [ ] 6.3 Correct this change's row in `openspec/changes/README.md`, which still
      records an open decision gate on the rate asset and a partial delta.

## 7. Validation

- [ ] 7.1 **Unit.** Exact-decimal comparator behaviour directly: bounds at, above,
      and below a value; inclusive against exclusive at equality; a value with more
      significant digits than a double holds; and a resolved listing value of the
      wrong shape.
- [ ] 7.2 **Unit.** Co-requirement declaration validation: unknown target,
      self-reference, cycle, one-directional supply, and criterion construction for
      a satisfied co-requirement.
- [ ] 7.3 **Unit.** Rate model validation and matching: missing rate, boundary
      values, a period outside the supported unit refused at publication, a rate
      missing its asset or period refused at publication, a listing quoting an
      unqueried asset excluded, and — with a synthetic second period injected — a
      cross-period query excluding rather than converting. The last case has no
      production path today and is what protects the rule when a second period
      arrives.
- [ ] 7.4 **Integration.** Exact decimal round-trip end to end: a high-precision
      amount published and queried through the canonical `RegistryClient` against
      the real registry app, matching or excluding on its true value. This is the
      claim task 5.1a previously mislabelled as unit — proving the client
      serializes it, HTTP parsing retains it, the registry builds the criterion, and
      a decimal-text listing value compares exactly is integration under
      `TESTING.md`, and a direct comparator test does not establish it.
- [ ] 7.5 **Integration.** A valid three-part rate query through the canonical
      `RegistryClient`; and a narrow raw-ASGI request supplying an amount bound
      without its asset, to prove the registry itself refuses rather than relying on
      client-side validation. The raw request is the rejection-contract exception
      `TESTING.md` permits.
- [ ] 7.6 **Integration.** Seller authoring through the real pool administration
      client and projection: a declared asking rate reaches the storefront
      publication candidate and then the registry. A mocked candidate dictionary
      does not establish this contract.
- [ ] 7.7 **Integration.** No-default-off-site: a storefront configured with a
      pricing default publishes for a remote origin's pool that declares no rate,
      and the listing carries none.
- [ ] 7.8 **Integration.** Rate lifecycle: change amount, asset, and period and
      confirm the existing listing is republished under its intended identity;
      remove the declaration and confirm the listing remains discoverable but absent
      from rate-bounded queries.
- [ ] 7.9 **Integration.** A malformed declaration fails its pool closed rather
      than publishing a fallback or a rateless listing.
- [ ] 7.10 **Integration.** No settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate, and a published
      asking rate is not populated from a mechanism rate. Exercise through the real
      storefront composition.
- [ ] 7.11 **Integration.** A listing advertising a rateless option publishes an
      asking rate and is returned by a rate-bounded query while its option remains
      rateless. This is the case a filter over the settlement carrier could not have
      served.
- [ ] 7.12 **System.** A buyer query bounded by rate returns backed and unbacked
      listings together and excludes listings publishing no rate. This requires the
      deployed multi-service environment; an in-process app does not establish it.
- [ ] 7.13 **System.** Multi-seller provenance: one storefront publishing for two
      seller sites, each site's declared asking rate reaching only its own listings.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why nothing is constructed from the
      rate, why the asking rate is not derived from a mechanism rate, and why a
      malformed declaration fails closed against the resolver's fall-through
      convention — not any claim about how much a buyer should trust either rate.
- [ ] 8.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the two engine capabilities
      landed in `registry-discovery` and the provenance rules in
      `storefront-publication`, rather than both in one capability.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and the accepted rate-honesty, two-disagreeing-prices,
      no-default-off-site, and hourly-only risks with their revisit triggers. The
      asset, engine, and authority decisions are recorded in `design.md`; do not
      restate their reasoning here.
- [ ] 8.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md`. The current-state price sentence is corrected
      earlier, in task 6.2. If this closes Goal 7's last gap, the goal is removed
      and its result absorbed into permanent documentation rather than left as an
      empty table — check the remaining rows before deciding.
- [ ] 8.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 8.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An exact-decimal declared value type whose comparison never passes through binary floating point | `openspec/specs/registry-discovery/spec.md` |
| Declarative filter co-requirements, resolved from the specification by registry and buyer alike | `openspec/specs/registry-discovery/spec.md` |
| The asking rate's frozen shape: decimal-text amount, opaque asset, supported time-rate period, all required together | `openspec/specs/registry-discovery/spec.md` |
| The published rate is a listing attribute, not a settlement option rate: nothing is constructed from it | `openspec/specs/registry-discovery/spec.md` |
| The asking rate and a mechanism rate are independent carriers; neither is derived from the other | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period and the asset rather than normalizing across them | `openspec/specs/registry-discovery/spec.md` |
| A listing publishing no rate is excluded from a rate-bounded query | `openspec/specs/registry-discovery/spec.md` |
| The asking rate is declared at the listing's origin pool; storefront override and default apply to home-site pools only | `openspec/specs/storefront-publication/spec.md` |
| A malformed asking-rate declaration fails its pool closed | `openspec/specs/storefront-publication/spec.md` |
| An asking-rate change republishes the listing in place through source publication | `openspec/specs/storefront-publication/spec.md` |
