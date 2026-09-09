## Why

`unbacked-listing-publication` makes supply the marketplace cannot admit against
discoverable. It does not make it comparable. A buyer can find unbacked listings
and filter them by region, GPU model, and form factor, but not by price, because
no compute listing publishes one.

That gap is the difference between a catalogue and a directory. Goal 7's value
statement is that a buyer gets one place to compare rates across backed and
unbacked supply; without a published rate, the goal delivers half of it.

The rate is separated from that change because it is a distinct buyer-facing
surface, not because it waits on one. An earlier version of this proposal made it
depend on `capacity-shape-pricing`, on the reasoning that a rate belongs inside the
family-grouped capability shape that change is building. That was a misreading of
what `capacity-shape-pricing` is for: it exists so a seller can put a number on a
shape a **buyer proposes during negotiation**, which is why it builds per-dimension
rates, an injectable aggregator, and a negotiated rate multiplier. A listing's
advertised shape does not vary — `_reject_unsupported_resource_shape_request`
rejects any buyer who names one, precisely because seller policy prices only the
advertised shape — so a published asking price for that listing is one number.

Nothing about publishing it requires decomposing a shape into per-dimension rates.
A buyer wanting to compare cost per GPU-hour across differently-shaped listings
derives it from this rate and the dimensions `publish-multidimensional-listing-shape`
publishes, which is a buyer-client computation rather than a seller decomposition.

## What Changes

- Publish a seller's asking rate for a compute listing's advertised shape in
  `offer_resource`, as a rate with its asset and its unit of time. One rate per
  listing, because a listing's advertised shape does not vary.
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
  asking rate too, and confining it would make the field mean "unbacked" a second
  time.
- Do not unbundle the rate across dimensions. A seller who prices RAM and GPUs
  differently cannot express that here, and a buyer comparing two listings that
  bundle different RAM is comparing bundled prices. That limitation is accepted for
  this version and belongs to `capacity-shape-pricing`, which is building the
  machinery for it; inventing a second decomposition here would be the duplication
  that change exists to prevent.

## Impact

- Affected code: the compute domains' publication candidate derivation and the
  registry filter evaluation.
- Affected specification: `openspec/specs/registry-discovery/spec.md`.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains fields and
  filters; the etag changes and buyers re-fetch, without a version bump.
- Not affected: settlement options, escrow terms, negotiation policy, or any
  agreed amount.

## Dependencies and Related Changes

- **Depends on `unbacked-listing-publication`**, which makes the listings this
  change prices publishable and establishes the backing field alongside which the
  rate is filtered.
- **Forward-compatible with `capacity-shape-pricing`**, not dependent on it. When a
  listing carries a minimum rate structure, this published field becomes that
  structure evaluated at the listing's advertised shape. The number's source
  changes; the published field does not, so no schema migration follows.
- Coordinate with `publish-multidimensional-listing-shape`, which publishes the
  dimensions a buyer divides this rate by to compare across shapes. No ordering
  dependency: a rate is comparable without them, and less useful.

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
