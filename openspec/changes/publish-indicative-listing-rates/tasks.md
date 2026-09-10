# Tasks — publish indicative listing rates

Depends on `unbacked-listing-publication`. Do not begin Section 2 before it has
landed.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Settled decisions to confirm against code

No decision gate remains open. Periods, filter semantics, the carrier separation,
and the asset expression are all settled in `design.md`; the tasks below confirm
the code facts each decision rests on still hold, and stop rather than proceed if
one has moved.

- [ ] 1.1 Confirm `PER_UNIT_SECONDS` still holds exactly `{"hour": 3600}` at
      implementation time. The hourly-only decision is parity with what the VM and
      bare-metal domains support, and a second entry appearing there changes what
      parity means rather than merely widening an option.
- [ ] 1.2 Confirm `SettlementPublicationClause` still expresses a published rate as
      an opaque `asset` string, positive decimal `rate` text without an exponent,
      and a canonical lowercase `per`, with rate and unit required together. The
      asking rate reuses that vocabulary rather than stating a second one; if the
      clause has changed shape, the asking rate follows it rather than diverging.
- [ ] 1.3 Confirm the settlement clause grammar still restricts `asset` to equality
      operators. The exclude-rather-than-convert rule for assets depends on no
      surface ordering or converting them.
- [ ] 1.4 Confirm `contact-exchange.v1` options remain rateless. A listing whose
      only mechanism declines scalar participation is the case that makes a separate
      listing-level field necessary rather than a filter over the settlement
      carrier; if that mechanism gains a rate, revisit the carrier decision before
      implementing.

## 2. Published shape

- [ ] 2.1 Publish one asking rate for the listing's advertised shape, carrying its
      amount, asset, and period. Do not decompose it per dimension — that is
      `capacity-shape-pricing`'s work for the negotiation side, and a second
      decomposition here would duplicate it.
- [ ] 2.1a Confirm the field is expressible as a rate structure evaluated at the
      advertised shape, so `capacity-shape-pricing` can later change where the
      number comes from without changing the published field.
- [ ] 2.1b Draw the period from `PER_UNIT_SECONDS` rather than a private list, so a
      published period and a settlement period cannot diverge. Refuse a period
      outside it rather than storing an uninterpretable value. In practice this means
      `hour` only; the constraint is written against the vocabulary so a second entry
      widens both surfaces at once.
- [ ] 2.1c Carry the asset as an opaque non-empty identifier of the same kind
      `settlement_options[*].asset` already carries. Do not require a contract
      address, decimals, or a chain identity, and do not interpret the identifier
      beyond equality comparison — an asking rate quoted in an off-chain currency
      must be expressible, since hosted fiat is already a registered mechanism and
      out-of-band supply is commonly priced in one.
- [ ] 2.1d Carry the amount as decimal text. Base units need a companion decimals
      field to be read, and a numeric encoding is lossy: 18-decimal base units pass
      2^53 at ordinary values, JSON numbers are doubles in most parsers, and SQLite
      INTEGER is int64. Reuse the repository's existing decimal-text convention
      rather than adding a second one.
- [ ] 2.1e Refuse publication of a rate missing its asset or its period. All three
      parts travel together, mirroring the existing rate-and-unit-together
      invariant on the settlement publication clause.
- [ ] 2.2 Publish it for backed and unbacked listings alike. Confining it to
      unbacked listings would make its presence a second encoding of backing.
- [ ] 2.3 Confirm the rate does not reach settlement options, escrow terms, or any
      accepted-obligation content.
- [ ] 2.4 Do not populate the asking rate from a mechanism rate, and do not write a
      published asking rate into a settlement carrier. Both directions are refused:
      deriving either would make the field's provenance unreadable, and it is
      undefinable for a listing advertising escrows in several assets at several
      rates. Keep the asking rate seller-stated publication input.
- [ ] 2.5 Confirm a listing carrying both an asking rate and a mechanism rate
      publishes without either being reconciled against the other, and that a
      disagreement between them is not a publication error. The relationship is
      stated, not enforced; see `design.md`.

## 3. Filters

- [ ] 3.1 Add exact `on_missing: fail` rate filters to
      `core/registry/filter-spec.yaml`, matching the convention every other
      published-shape filter uses. Note this change lands after
      `settle-listing-vocabulary`, so the paths are `listing_resource`.
- [ ] 3.1a Make a rate-bounded query name its period and match only listings quoting
      it. Do not convert across periods. With one period in the vocabulary this has
      no observable effect today; it is implemented now so adding a second period
      does not silently turn every hourly query into a cross-period comparison.
- [ ] 3.1b Make a rate-bounded query name its asset and match only listings quoting
      it, with equality comparison only. Do not convert across assets: conversion
      needs an external exchange rate that moves continuously, would make one
      query's result depend on when it ran, and would make the registry an authority
      on relative asset value.
- [ ] 3.1c Refuse a rate bound that names no asset or no period rather than
      evaluating it against an unstated dimension.
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
- [ ] 4.1a State that the asking rate and a mechanism rate are independent
      carriers: not required to agree, neither correcting the other, and neither
      derived from the other. This is the statement that keeps a listing carrying
      both from having two prices with no stated relationship.
- [ ] 4.1b State the rate's three-part shape — amount as decimal text, opaque asset
      identifier, period from the canonical vocabulary — and that all three are
      required together.
- [ ] 4.2 Add a scenario for a rate-bounded query against a listing publishing no
      rate.
- [ ] 4.3 Add a scenario confirming no settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate.
- [ ] 4.4 Add a scenario for a rate quoted in an asset with no contract address,
      decimals, or chain identity, so the off-chain case is normative rather than
      incidental.

## 5. Validation

- [ ] 5.1 **Unit.** Exhaustive rate-filter matching: missing rate, boundary values,
      a period outside the canonical vocabulary refused at publication, a rate
      missing its asset or period refused at publication, a query bound missing its
      asset or period refused, a listing quoting an unqueried asset excluded, and —
      with a synthetic second period injected into the vocabulary — a cross-period
      query excluding rather than converting. The last case has no production path
      today and is the one that protects the rule when a second period arrives.
- [ ] 5.1a **Unit.** A decimal-text amount large enough to lose precision as a
      double or overflow int64 round-trips through publication and filtering
      exactly. This is the reason for the encoding and the regression that would
      otherwise appear only at 18-decimal scale.
- [ ] 5.2 **Integration.** Publish and query rates through the canonical
      `RegistryClient` against the real registry app.
- [ ] 5.3 **Integration.** Confirm no settlement option, escrow term, or accepted
      obligation carries a value derived from the published rate, and that a
      published asking rate is not populated from a mechanism rate.
- [ ] 5.3a **Integration.** A listing advertising a rateless option publishes an
      asking rate and is returned by a rate-bounded query, while its option remains
      rateless. This is the case a filter over the settlement carrier could not
      have served.
- [ ] 5.4 **System.** A buyer query bounded by rate returns backed and unbacked
      listings together and excludes listings publishing no rate.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why nothing is constructed from the
      rate, and why the asking rate is not derived from a mechanism rate — not any
      claim about how much a buyer should trust either.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. That nothing is constructed from the
      rate, and that the two carriers are independent, are both behaviour
      implementations must satisfy, so confirm they landed as normative
      requirements rather than as design prose.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and the accepted rate-honesty, two-disagreeing-prices, and
      hourly-only risks with their revisit triggers. The asset and carrier
      decisions are recorded in `design.md`; do not restate their reasoning here.
- [ ] 6.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md`, and correct the goal's statement that "no
      compute listing publishes a price at all" — a price is published today inside
      the escrow and settlement-option rate carriers, and what this change adds is a
      listing-level asking rate and the first filter over a rate value. If this
      closes Goal 7's last gap, the goal is removed and its result absorbed into
      permanent documentation rather than left as an empty table — check the
      remaining rows before deciding.
- [ ] 6.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The published rate is a listing attribute, not a settlement option rate: nothing is constructed from it | `openspec/specs/registry-discovery/spec.md` |
| A listing publishing no rate is excluded from a rate-bounded query | `openspec/specs/registry-discovery/spec.md` |
| A published rate carries its period from the canonical time-unit vocabulary | `openspec/specs/registry-discovery/spec.md` |
| A published rate carries an opaque asset identifier and a decimal-text amount, all three parts required together | `openspec/specs/registry-discovery/spec.md` |
| The asking rate and a mechanism rate are independent carriers; neither is derived from the other | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period and the asset rather than normalizing across them | `openspec/specs/registry-discovery/spec.md` |
