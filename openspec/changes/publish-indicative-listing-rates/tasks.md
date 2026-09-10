# Tasks — publish indicative listing rates

Depends on `unbacked-listing-publication`. Do not begin Section 2 before it has
landed.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Decision gate

Periods and filter semantics are settled; `design.md` carries the reasoning. The
asset question remains open and is why the spec delta covers the period and filter
rules but not the field's full shape.

- [ ] 1.1 **Decide how the rate's asset is expressed and whether a rate-bounded
      query carries one**, and record the reasoning in `design.md`. A listing already
      names assets in its settlement options; reusing that vocabulary or stating a
      separate one is a decision, not a default. Complete the spec delta once it is
      resolved.
- [ ] 1.2 Confirm `PER_UNIT_SECONDS` still holds exactly `{"hour": 3600}` at
      implementation time. The hourly-only decision is parity with what the VM and
      bare-metal domains support, and a second entry appearing there changes what
      parity means rather than merely widening an option.

## 2. Published shape

- [ ] 2.1 Publish one asking rate for the listing's advertised shape, with its
      asset and period. Do not decompose it per dimension — that is
      `capacity-shape-pricing`'s work for the negotiation side, and a second
      decomposition here would duplicate it.
- [ ] 2.1b Draw the period from `PER_UNIT_SECONDS` rather than a private list, so a
      published period and a settlement period cannot diverge. Refuse a period
      outside it rather than storing an uninterpretable value. In practice this means
      `hour` only; the constraint is written against the vocabulary so a second entry
      widens both surfaces at once.
- [ ] 2.1a Confirm the field is expressible as a rate structure evaluated at the
      advertised shape, so `capacity-shape-pricing` can later change where the
      number comes from without changing the published field.
- [ ] 2.2 Publish it for backed and unbacked listings alike. Confining it to
      unbacked listings would make its presence a second encoding of backing.
- [ ] 2.3 Confirm the rate does not reach settlement options, escrow terms, or any
      accepted-obligation content.

## 3. Filters

- [ ] 3.1 Add exact `on_missing: fail` rate filters to
      `core/registry/filter-spec.yaml`, matching the convention every other
      published-shape filter uses. Note this change lands after
      `settle-listing-vocabulary`, so the paths are `listing_resource`.
- [ ] 3.1a Make a rate-bounded query name its period and match only listings quoting
      it. Do not convert across periods. With one period in the vocabulary this has
      no observable effect today; it is implemented now so adding a second period
      does not silently turn every hourly query into a cross-period comparison.
- [ ] 3.2 Confirm a listing publishing no rate is excluded from a rate-bounded
      query rather than passing it.
- [ ] 3.3 Record the etag consequence: adding filters changes the spec's etag and
      buyers re-fetch, without a version bump.

## 4. Specification

- [ ] 4.1 State in `openspec/specs/registry-discovery/spec.md` that the published
      rate is a listing attribute and not a settlement option rate: no settlement
      option, escrow term, or accepted obligation is constructed from it, and an
      agreed amount is absent until negotiated. Write it as a statement about what
      the system builds, not about how strong the claim is — every published field
      is a seller assertion and the spec must not imply otherwise.
- [ ] 4.2 Add a scenario for a rate-bounded query against a listing publishing no
      rate.
- [ ] 4.3 Add a scenario confirming no settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate.

## 5. Validation

- [ ] 5.1 **Unit.** Exhaustive rate-filter matching: missing rate, boundary values,
      a period outside the canonical vocabulary refused at publication, and — with a
      synthetic second period injected into the vocabulary — a cross-period query
      excluding rather than converting. The last case has no production path today
      and is the one that protects the rule when a second period arrives.
- [ ] 5.2 **Integration.** Publish and query rates through the canonical
      `RegistryClient` against the real registry app.
- [ ] 5.3 **Integration.** Confirm no settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate.
- [ ] 5.4 **System.** A buyer query bounded by rate returns backed and unbacked
      listings together and excludes listings publishing no rate.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why nothing is constructed from the
      rate — not any claim about how much a buyer should trust it.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. That nothing is constructed from the
      rate is behaviour implementations must satisfy, so confirm it landed as a
      normative requirement rather than as design prose.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the asset decision from 1.1, and the accepted rate-honesty and
      hourly-only risks with their revisit triggers.
- [ ] 6.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md`. If this closes Goal 7's last gap, the goal
      is removed and its result absorbed into permanent documentation rather than
      left as an empty table — check the remaining rows before deciding.
- [ ] 6.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The published rate is a listing attribute, not a settlement option rate: nothing is constructed from it | `openspec/specs/registry-discovery/spec.md` |
| A listing publishing no rate is excluded from a rate-bounded query | `openspec/specs/registry-discovery/spec.md` |
| A published rate carries its period from the canonical time-unit vocabulary | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period rather than normalizing across it | `openspec/specs/registry-discovery/spec.md` |
