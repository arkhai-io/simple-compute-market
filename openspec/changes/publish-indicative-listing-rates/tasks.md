# Tasks — publish indicative listing rates

Depends on `capacity-shape-pricing` and `unbacked-listing-publication`. Do not
begin Section 2 before both have landed.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Decision gates

- [ ] 1.1 **Decide which rate periods are expressible and whether the filter
      normalizes across them**, and record the reasoning in `design.md`. It is an
      open question there. A filter comparing an hourly rate against a monthly one
      without normalizing is worse than no filter, so this must not be settled by
      an implementation default.
- [ ] 1.2 **Decide whether a rate-bounded query carries a currency or token
      dimension**, and record the reasoning. Likely answered by
      `capacity-shape-pricing`'s vocabulary; confirm rather than assume.

## 2. Published shape

- [ ] 2.1 Publish the indicative rate on `capacity-shape-pricing`'s
      family-grouped capability shape. Do not introduce a private scalar
      representation, even if the family-grouped shape is more work for this
      change's own needs.
- [ ] 2.2 Publish it for backed and unbacked listings alike. Confining it to
      unbacked listings would make its presence a second encoding of backing.
- [ ] 2.3 Confirm the rate does not reach settlement options, escrow terms, or any
      accepted-obligation content.

## 3. Filters

- [ ] 3.1 Add exact `on_missing: fail` rate filters to
      `core/registry/filter-spec.yaml`, matching the convention every other
      `offer_resource` filter uses.
- [ ] 3.2 Confirm a listing publishing no rate is excluded from a rate-bounded
      query rather than passing it.
- [ ] 3.3 Record the etag consequence: adding filters changes the spec's etag and
      buyers re-fetch, without a version bump.

## 4. Specification

- [ ] 4.1 State in `openspec/specs/registry-discovery/spec.md` that the published
      rate is indicative: a listing attribute, not a settlement option rate, with
      no agreed amount implied and none constructed from it.
- [ ] 4.2 Add a scenario for a rate-bounded query against a listing publishing no
      rate.
- [ ] 4.3 Add a scenario confirming two listings advertising the same rate have
      made the same claim rather than the same commitment — expressed as the
      absence of any obligation or option derived from the field.

## 5. Validation

- [ ] 5.1 **Unit.** Exhaustive rate-filter matching, including missing rate,
      boundary values, and whichever period and currency cases Section 1 settles.
- [ ] 5.2 **Integration.** Publish and query rates through the canonical
      `RegistryClient` against the real registry app.
- [ ] 5.3 **Integration.** Confirm no settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate.
- [ ] 5.4 **System.** A buyer query bounded by rate returns backed and unbacked
      listings together and excludes listings publishing no rate.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why the rate is not a settlement
      option rate.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. The indicative status states
      behaviour implementations must satisfy, so confirm it landed as a normative
      requirement rather than as design prose.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the two Section 1 decision outcomes, and the accepted
      rate-honesty risk with its revisit trigger.
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
| The published rate is indicative — a listing attribute, not a settlement option rate | `openspec/specs/registry-discovery/spec.md` |
| A listing publishing no rate is excluded from a rate-bounded query | `openspec/specs/registry-discovery/spec.md` |
