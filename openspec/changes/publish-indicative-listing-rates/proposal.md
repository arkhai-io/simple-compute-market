## Why

`unbacked-listing-publication` makes supply the marketplace cannot admit against
discoverable. It does not make it comparable. A buyer can find unbacked listings
and filter them by region, GPU model, and form factor, but not by price.

That gap is the difference between a catalogue and a directory. Goal 7's value
statement is that a buyer gets one place to compare rates across backed and
unbacked supply; without a comparable rate, the goal delivers half of it.

Being precise about the gap matters, because the imprecise version points at the
wrong fix. A seller-advertised price is already published — inside the settlement
carriers. `AcceptedEscrow.rates` is documented as the canonical pricing
advertisement and carries a per-hour price; `settlement_options[*].rates` carries
the mechanism-neutral equivalent alongside a required `asset`. What does not exist
is any filter over a rate *value*: every rate-adjacent filter in
`filter-spec.yaml` reads `literal_fields.token` or `mechanism`, never an amount.

So there are two gaps rather than one, and only a listing-level field closes both.
The first is that no rate is filterable. The second is that the supply this change
exists to serve has no rate to filter: an out-of-band deal settles through
`contact-exchange.v1`, whose options are rateless because the mechanism declines
scalar participation, so those listings carry no escrow rate and no option rate at
all. A filter over the settlement carrier would leave precisely the target supply
uncomparable while making the settlement carrier the comparison surface. See
`design.md`.

The rate is separated from `unbacked-listing-publication` because it is a distinct
buyer-facing surface, not because it waits on one. An earlier version of this
proposal made it depend on `capacity-shape-pricing`, on the reasoning that a rate
belongs inside the family-grouped capability shape that change is building. That was
a misreading of what `capacity-shape-pricing` is for: it exists so a seller can put a
number on a shape a **buyer proposes during negotiation**, which is why it builds
per-dimension rates, an injectable aggregator, and a negotiated rate multiplier. A
listing's advertised shape does not vary — `_reject_unsupported_resource_shape_request`
rejects any buyer who names one, precisely because seller policy prices only the
advertised shape — so a published asking price for that listing is one number.

Nothing about publishing it requires decomposing a shape into per-dimension rates.
A buyer wanting to compare cost per GPU-hour across differently-shaped listings
derives it from this rate and the dimensions `publish-multidimensional-listing-shape`
publishes, which is a buyer-client computation rather than a seller decomposition.

## What Changes

- Publish a seller's asking rate for a compute listing's advertised shape in the
  published listing shape, as an amount with the asset it is quoted in and the
  period it is quoted per. All three parts are required together: an amount alone
  cannot be read and a bound cannot be evaluated against it. One rate per listing,
  because a listing's advertised shape does not vary.
- Carry the asset as an opaque, non-empty identifier of the same kind a settlement
  option's published asset already carries, rather than as structured token
  metadata. Structured metadata presumes an on-chain ERC-20; hosted fiat is already
  a registered mechanism and out-of-band supply is commonly priced in a currency,
  so an asking rate must be expressible without a contract address, decimals, or a
  chain identity.
- Carry the amount as decimal text rather than as a number or as base units. Base
  units need a companion decimals field to be read, and a numeric encoding is lossy
  at ordinary values — 18-decimal base units pass what a double or an int64 holds.
  This reuses the repository's existing decimal-text convention.
- Draw the period from the canonical time-unit vocabulary settlement rates already
  use, which currently holds only `hour` — parity with what the VM and bare-metal
  domains support, since both compute against an inline hourly divisor. A seller
  pricing monthly cannot express it in this version.
- Match rate filters on the period and the asset rather than normalizing across
  either. A buyer shopping hourly is not asking for supply quoted monthly, because
  a monthly quote signals a monthly commitment. Cross-asset comparison additionally
  requires an external exchange rate that moves continuously, which would make one
  query's result depend on when it ran and make the registry an authority on
  relative asset value.
- Add exact, fail-on-missing rate filters to `core/registry/filter-spec.yaml`,
  matching the convention every other `listing_resource` filter uses.
- State normatively that the published rate is a **listing attribute** and not a
  settlement option rate: no settlement option, escrow term, or accepted obligation
  is constructed from it, and an agreed amount is absent rather than zero until one
  is negotiated. This describes what the system builds from the number, not how
  much a buyer should believe it — like every published field, a rate is a seller
  assertion, and nothing in the marketplace verifies any of them.
- State normatively that the asking rate and any rate a listing advertises inside a
  settlement carrier are independent: not required to agree, neither correcting the
  other, and neither derived from the other. A listing may legitimately carry both,
  and without a stated relationship it would be publishing two prices with none.
- State that a listing publishing no rate is excluded from a rate-bounded query
  rather than passing it, and that a rate bound naming no asset or no period is
  refused rather than evaluated.

## Capabilities

### Modified Capabilities

- `registry-discovery`: the compute listing shape carries the seller's asking rate
  on the family-grouped capability shape as an amount, asset, and period,
  filterable exactly and fail-on-missing, with its independence from the settlement
  carriers normative.

### New Capabilities

None.

## Non-Goals

- Do not make the rate a settlement option rate, and do not add scalar
  participation to a mechanism that declines it. The two are different carriers
  with different guarantees; see `design.md`.
- Do not describe the published rate as a weaker class of claim than any other
  published field. Every published field is a seller assertion; the only real
  distinctions are what the system constructs from a value and whether anything is
  exhausted. Claim-strength vocabulary must not enter the schema, the filter names,
  or the specification.
- Do not add a filter over an escrow or settlement-option rate value. That is a
  different feature with its own reasoning about the settlement carrier, and it is
  not what makes out-of-band supply comparable.
- Do not enforce consistency between the asking rate and a mechanism rate. A
  listing accepting several escrows in several assets has no single floor for an
  equality rule to name, and the rule would fire only where a seller has already
  said the same thing twice.
- Do not build a rate-honesty control, and do not imply one exists. Registry
  curation is the control for a misleading rate exactly as it is for a misleading
  compute shape, it sits outside the registry service boundary, and it is out of
  band in both cases.
- Do not change negotiation-floor pricing policy, which is a separate
  storefront-side resolution with its own three-tier precedence.
- Do not restrict the rate to unbacked listings. A backed listing may publish an
  asking rate too, and confining it would make the field mean "unbacked" a second
  time.
- Do not add a time period to the settlement vocabulary. Widening
  `PER_UNIT_SECONDS` touches every arithmetic path that reads it and is settlement
  work rather than publication work.
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
- Affected sequencing: lands after `settle-listing-vocabulary`, so the published
  shape is `listing_resource` and its offering-mode field is `offering_mode`.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains fields and
  filters; the etag changes and buyers re-fetch, without a version bump.
- Affected roadmap text: Goal 7 records that "no compute listing publishes a price
  at all", which is imprecise for the reason given above and is corrected at
  closeout.
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
- Reuses the published-rate vocabulary `kit/settlement-runtime`'s settlement
  publication clause already defines — opaque asset, decimal-text rate, canonical
  unit, all supplied together. No dependency: the vocabulary is read, not changed.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; a published listing
      attribute is subsystem behaviour rather than a repository-wide boundary.
      Re-confirm at implementation time rather than assuming.
- [x] Existing subsystem specification —
      `openspec/specs/registry-discovery/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The published rate is a listing attribute, not a settlement option rate: nothing
  is constructed from it and an agreed amount is absent until negotiated —
  `openspec/specs/registry-discovery/spec.md`.
- The asking rate and a mechanism rate are independent carriers; neither is derived
  from the other — `openspec/specs/registry-discovery/spec.md`.
- A published rate carries an amount as decimal text, an opaque asset identifier,
  and a period from the canonical vocabulary, all required together —
  `openspec/specs/registry-discovery/spec.md`.
- A listing publishing no rate is excluded from a rate-bounded query rather than
  passing it, and a rate bound naming no asset or period is refused —
  `openspec/specs/registry-discovery/spec.md`.
