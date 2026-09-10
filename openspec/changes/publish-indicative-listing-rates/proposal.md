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
uncomparable while making the settlement carrier the comparison surface.

**The generic registry also cannot evaluate the field this change publishes, so
two filter-engine capabilities are in scope here.** Range bounds and range
evaluation are float-typed and float-parsed, and range evaluation reads only
resolved values that are already `int` or `float` — so a decimal-text listing value
matches no range at all. And `FilterDecl` has no relationship between filters, so
"a rate bound requires an asset and a period" has no declarative expression.
Neither is fixable locally: `registry-discovery` requires the buyer compiler to
resolve every rule from the active filter specification and add no domain fields,
so a conditional naming this change's field in generic code would violate a
normative requirement. See `design.md`.

The rate is separated from `unbacked-listing-publication` because it is a distinct
buyer-facing surface with its own asset, period, filter, and authoring decisions —
not because it waits on other shape work. An earlier version of this proposal made
it depend on `capacity-shape-pricing`, on the reasoning that a rate belongs inside
the family-grouped capability shape that change is building. That was a misreading
of what `capacity-shape-pricing` is for: it exists so a seller can put a number on
a shape a **buyer proposes during negotiation**, which is why it builds
per-dimension rates, an injectable aggregator, and a negotiated rate multiplier. A
listing's advertised shape does not vary — `_reject_unsupported_resource_shape_request`
rejects any buyer who names one, precisely because seller policy prices only the
advertised shape — so a published asking price for that listing is one number.

## What Changes

- Publish a seller's asking rate for a compute listing's advertised shape as an
  `asking_rate` object on the published listing resource, carrying an `amount`, the
  `asset` it is quoted in, and the `period` it is quoted per. All three are
  required together. One rate per listing, as a catalogue price for a shape that
  does not vary, not nested under a capability family.
- Carry the asset as an opaque, non-empty identifier of the same kind a settlement
  option's published asset already carries, rather than as structured token
  metadata. Structured metadata presumes an on-chain ERC-20; hosted fiat is already
  a registered mechanism and out-of-band supply is commonly priced in a currency,
  so an asking rate must be expressible without a contract address, decimals, or a
  chain identity.
- Carry the amount as exact decimal text. A binary float cannot represent ordinary
  decimal prices, and a base-unit integer cannot express a fraction, needs a
  companion decimals field, and overflows 64 bits at 18-decimal scale.
- Accept `hour` as the period. This is a local asking-rate contract validated
  against the settlement time-scaling table for parity, not a rule inherited from
  it: a seller pricing monthly cannot express it in this version, and accepting a
  further period stays a decision rather than a side effect of a settlement change.
- **Extend the generic filter-specification vocabulary with an exact-decimal
  declared value type** whose wire representation is a JSON string and whose
  comparison domain is exact decimal, leaving the existing JSON-number type's
  semantics untouched. The buyer client already renders decimals exactly, so the
  work is server-side plus one mapping entry.
- **Extend it with declarative filter co-requirements**, so a bound can name the
  filters that must accompany it and both the registry and the buyer compiler
  resolve the rule from the specification rather than from code.
- Declare `asking_rate_max`, `asking_rate_min`, `asking_rate_asset`, and
  `asking_rate_period` in `core/registry/filter-spec.yaml`, all fail-on-missing,
  with both bounds co-requiring the asset and period.
- Match rate filters on the period and the asset rather than normalizing across
  either. A buyer shopping hourly is not asking for supply quoted monthly, because
  a monthly quote signals a monthly commitment. Cross-asset comparison
  additionally requires an external exchange rate that moves continuously, which
  would make one query's result depend on when it ran and make the registry an
  authority on relative asset value.
- **Author the rate at the listing's origin site**, as a declaration on the
  Resource Pool the listing derives from, carried in the already projected
  domain-owned `pricing` policy tag. A storefront-local override and a
  storefront-wide default resolve only for the storefront's own home-site pools and
  never for a pool at another origin.
- Fail a pool closed on a malformed or partial declaration, and publish no rate
  where none is declared and no default applies.
- Republish derived listings in place when a declared rate changes or is removed,
  through source-publication reconciliation rather than capacity reconciliation.
- State normatively that the published rate is a **listing attribute** and not a
  settlement option rate: no settlement option, escrow term, or accepted obligation
  is constructed from it, and an agreed amount is absent rather than zero until one
  is negotiated. This describes what the system builds from the number, not how
  much a buyer should believe it — like every published field, a rate is a seller
  assertion, and nothing in the marketplace verifies any of them.
- State normatively that the asking rate and any rate a listing advertises inside a
  settlement carrier are independent: not required to agree, neither correcting the
  other, and neither derived from the other.
- State that a listing publishing no rate is excluded from a rate-bounded query
  rather than passing it, and that a rate bound naming no asset or no period is
  refused rather than evaluated.

## Capabilities

### Modified Capabilities

- `registry-discovery`: the filter grammar gains an exact-decimal declared value
  type and declarative filter co-requirements; the compute listing shape carries
  the seller's asking rate as a frozen three-part object, filterable exactly and
  fail-on-missing, with its independence from the settlement carriers normative.
- `storefront-publication`: the asking rate is declared at the listing's origin
  pool and read from the projection, storefront override and default apply to
  home-site pools only, a malformed declaration fails its pool closed, the rate is
  never derived from or written into a settlement carrier, and a rate change
  republishes the listing in place.

### New Capabilities

None.

## Non-Goals

- Do not make the rate a settlement option rate, and do not add scalar
  participation to a mechanism that declines it.
- Do not describe the published rate as a weaker class of claim than any other
  published field. Every published field is a seller assertion; the only real
  distinctions are what the system constructs from a value and whether anything is
  exhausted. Claim-strength vocabulary must not enter the schema, the filter names,
  or the specification.
- Do not change the existing `number` value type's comparison semantics. Other
  deployments' specifications declare it, and retyping it would change their
  behaviour silently.
- Do not encode this change's field, or any field, into generic registry or
  `RegistryClient` logic. Both new engine capabilities are declarative or they are
  not worth having.
- Do not add a filter over an escrow or settlement-option rate value. That is a
  different feature with its own reasoning about the settlement carrier.
- Do not enforce consistency between the asking rate and a mechanism rate. A
  listing accepting several escrows in several assets has no single floor for an
  equality rule to name.
- Do not apply a storefront-wide pricing default to a pool at another origin. That
  would advertise the aggregator's price as the seller's — a false assertion about
  another party's commercial position.
- Do not change `resource-pool-management`. It already declares `pricing` a
  domain-neutral opaque policy tag with unknown tags forward-compatible, so the
  domain owns the shape it reads inside it.
- Do not build a rate-honesty control, and do not imply one exists. Registry
  curation is the control for a misleading rate exactly as it is for a misleading
  compute shape, it sits outside the registry service boundary, and it is out of
  band in both cases.
- Do not change negotiation-floor pricing policy, which is a separate
  storefront-side resolution with its own three-tier precedence.
- Do not restrict the rate to unbacked listings. Confining it would make the field
  mean "unbacked" a second time.
- Do not add a time period to the settlement vocabulary. Widening
  `PER_UNIT_SECONDS` touches every arithmetic path that reads it and is settlement
  work rather than publication work.
- Do not unbundle the rate across dimensions. That limitation is accepted for this
  version and belongs to `capacity-shape-pricing`, which is building the machinery
  for it.

## Impact

- Affected code: the generic registry's filter specification model and filter
  evaluation, the buyer query compiler's type mapping, the compute domains'
  publication candidate derivation, and the VM domain's pricing resolution.
- Affected specification: `openspec/specs/registry-discovery/spec.md`,
  `openspec/specs/storefront-publication/spec.md`.
- Affected sequencing: lands after `settle-listing-vocabulary`, so the published
  shape is `listing_resource` and its offering-mode field is `offering_mode`. Within
  this change, the filter-engine work ships before any filter specification that
  uses it — a registry running the current engine fails to load a spec declaring
  the new type or `requires`, rather than ignoring them.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains fields and
  filters; the etag changes and buyers re-fetch, without a version bump.
- Affected cross-change text: `capacity-shape-pricing`'s single-rate compatibility
  reading is amended so it cannot be read as reinterpreting a published asking rate
  as a primary-dimension rate.
- Affected roadmap text: Goal 7 records that "no compute listing publishes a price
  at all", which is false today independent of this change and is corrected in the
  design branch rather than at closeout.
- Not affected: settlement options, escrow terms, negotiation policy, any agreed
  amount, `resource-pool-management`, or the existing `number` value type.

## Dependencies and Related Changes

- **Depends on `unbacked-listing-publication`**, which makes the listings this
  change prices publishable and establishes the backing field alongside which the
  rate is filtered, and whose source-publication reconciliation this change's rate
  lifecycle routes through.
- **Forward-compatible with `capacity-shape-pricing`**, not dependent on it. The
  two are distinct quantities: a listing-wide catalogue price and a per-dimension
  negotiation rate structure. A storefront may derive the former from the latter
  where seller policy says so; the structure never replaces, subsumes, or
  reinterprets it. That change's text is amended in this step to keep the two
  readable apart.
- Coordinate with `publish-multidimensional-listing-shape`, which publishes the
  dimensions a buyer divides this rate by to compare across shapes, and whose
  flattened convention the `asking_rate` object sits beside rather than inside. No
  ordering dependency.
- Reuses the published-rate vocabulary `kit/settlement-runtime`'s settlement
  publication clause already defines — opaque asset, decimal-text rate, unit
  supplied with the rate. No dependency: the vocabulary is read, not changed.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; a published listing
      attribute and a filter-grammar primitive are both subsystem behaviour rather
      than repository-wide boundaries. Re-confirm at implementation time rather than
      assuming.
- [x] Existing subsystem specification —
      `openspec/specs/registry-discovery/spec.md`,
      `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- An exact-decimal declared value type whose comparison never passes through binary
  floating point, leaving the JSON-number type unchanged —
  `openspec/specs/registry-discovery/spec.md`.
- Declarative filter co-requirements, resolved from the active specification by
  both the registry and the buyer compiler —
  `openspec/specs/registry-discovery/spec.md`.
- The asking rate's frozen shape: decimal-text amount, opaque asset identifier,
  supported time-rate period, all required together, one per listing —
  `openspec/specs/registry-discovery/spec.md`.
- The published rate is a listing attribute, not a settlement option rate: nothing
  is constructed from it and an agreed amount is absent until negotiated —
  `openspec/specs/registry-discovery/spec.md`.
- The asking rate and a mechanism rate are independent carriers; neither is derived
  from the other — `openspec/specs/registry-discovery/spec.md`.
- A listing publishing no rate is excluded from a rate-bounded query, and a rate
  bound naming no asset or period is refused —
  `openspec/specs/registry-discovery/spec.md`.
- The asking rate is declared at the listing's origin pool; storefront override and
  default apply to home-site pools only; a malformed declaration fails its pool
  closed; a rate change republishes in place —
  `openspec/specs/storefront-publication/spec.md`.
