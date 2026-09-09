## Why

`unbacked-listing-publication` makes supply the marketplace cannot admit against
discoverable. It does not make it comparable. A buyer can find unbacked listings
and filter them by region, GPU model, and form factor, but not by price, because
no compute listing publishes one.

That gap is the difference between a catalogue and a directory. Goal 7's value
statement is that a buyer gets one place to compare rates across backed and
unbacked supply; without a published rate, the goal delivers half of it.

The rate is separated from that change rather than carried by it because of its
shape rather than its substance. `capacity-shape-pricing` is moving rates into
the family-grouped capability shape and already has three consumers; a fourth
private scalar representation added to avoid waiting would have to be migrated
later by whoever touches pricing next. But `capacity-shape-pricing` is itself
blocked on `structured-capacity-requirements`, which is unstarted — so binding
discovery to that chain would block it behind two unstarted changes. Splitting
lets discovery proceed and keeps the rate on the shape it belongs on.

## What Changes

- Publish an indicative rate on compute listings in `offer_resource`, using
  `capacity-shape-pricing`'s family-grouped capability shape rather than a
  private scalar.
- Add exact, fail-on-missing rate filters to `core/registry/filter-spec.yaml`,
  matching the convention every other `offer_resource` filter uses.
- State normatively that the published rate is a **listing attribute** and not a
  settlement option rate: no settlement option, escrow term, or accepted obligation
  is constructed from it, and an agreed amount is absent rather than zero until one
  is negotiated. This describes what the system builds from the number, not how
  much a buyer should believe it — like every published field, a rate is a seller
  assertion, and nothing in the marketplace verifies any of them.
- State that a listing publishing no rate is excluded from a rate-bounded query
  rather than passing it.

## Capabilities

### Modified Capabilities

- `registry-discovery`: the compute listing shape carries an indicative rate on
  the family-grouped capability shape, filterable exactly and fail-on-missing,
  with its indicative status normative.

### New Capabilities

None.

## Non-Goals

- Do not make the rate a settlement option rate, and do not add scalar
  participation to a mechanism that declines it. The two are different carriers
  with different guarantees; see `design.md`.
- Do not build a rate-honesty control, and do not imply one exists. Registry
  curation is the control for a misleading rate exactly as it is for a misleading
  compute shape, it sits outside the registry service boundary, and it is out of
  band in both cases.
- Do not change negotiation-floor pricing policy, which is a separate
  storefront-side resolution with its own three-tier precedence.
- Do not restrict the rate to unbacked listings. A backed listing may publish an
  indicative asking rate too, and confining it would make the field mean
  "unbacked" a second time.

## Impact

- Affected code: the compute domains' publication candidate derivation and the
  registry filter evaluation.
- Affected specification: `openspec/specs/registry-discovery/spec.md`.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains fields and
  filters; the etag changes and buyers re-fetch, without a version bump.
- Not affected: settlement options, escrow terms, negotiation policy, or any
  agreed amount.

## Dependencies and Related Changes

- **Depends on `capacity-shape-pricing`** for the family-grouped rate shape, and
  transitively on `structured-capacity-requirements` for the vocabulary that
  change waits on.
- **Depends on `unbacked-listing-publication`**, which makes the listings this
  change prices publishable and establishes the backing field alongside which the
  rate is filtered.
- Coordinate with `publish-multidimensional-listing-shape`, which owns the
  dimension shape the rate attaches to.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; an indicative
      listing attribute is subsystem behaviour rather than a repository-wide
      boundary. Re-confirm at implementation time rather than assuming.
- [x] Existing subsystem specification —
      `openspec/specs/registry-discovery/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The published rate is a listing attribute, not a settlement option rate: nothing
  is constructed from it and an agreed amount is absent until negotiated —
  `openspec/specs/registry-discovery/spec.md`.
- A listing publishing no rate is excluded from a rate-bounded query rather than
  passing it — `openspec/specs/registry-discovery/spec.md`.
