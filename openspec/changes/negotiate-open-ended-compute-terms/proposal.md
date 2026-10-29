## Why

Compute buyers need a prepaid reserved term, or compute billed per period until they
stop, with or without a seller's right to stop on notice. Current compute terms
require a duration and project Alkahest's splitter onto listing-level markers. They
do not express these products across mechanisms or bound them by an absolute date.

## What Changes

- Derive reserved, on-demand and spot from billing kind and the selected option's
  payee entitlement. Use `agreed-evidence-and-early-termination`'s shared
  `early_termination` and `adjudication` codec, not an `interruption` object.
  Both are objects under the selected option's `lifecycle`, beside its `price` and
  `settlement` (D4; foundation D5, "The option's shape").
- One `agreed_price(agreement, listing)` accessor returns a quote with unit `total`
  or `per_period`, following `negotiation-driven-capacity-resize`'s multiplier
  contract. A fail-closed repository check refuses direct `Agreement.amount` reads
  outside the accessor and declared raw negotiation hooks.
- Keep listing-level `max_duration_seconds` and add `available_until_utc`, through
  hints, storefront overrides and configured defaults. For an unnamed recurring
  horizon, at the resolved start, `duration_seconds =
  min(max_duration, available_until - start)` over stated finite bounds, without
  rounding and with at least one whole period. Reserved deals must also satisfy both bounds.
- Publish one listing per existing capacity/shape identity with separately priced
  options for its billing/entitlement combinations. Omit unbounded recurring
  candidates without suppressing valid reserved ones.
- Gate publication, acceptance of cached selections and rate-part materialization
  on one composition-owned servicing declaration. Preserve servicing of accepted
  deals even when new offers are disabled.
- Both buyer CLIs show class, unit-bearing price, setup once charge, reserve,
  maximum term, entitlements/notices, per-stopper and term-end `settles_through`
  billing treatment and adjudication/retention terms. Compute term ends use
  `last_boundary` mapped to payments `end.partialPeriod: returned`, failing closed
  until vendored. Interim recommendation: an absolute end with a charged final
  partial period disclosed in the option.
  Buyer guarantees rest on authority records and kept signed bytes.
- Drop bare metal's minimum-spend gate. Presets use an honestly named setup `once`
  part beside the rate by default; sellers may refuse churners in negotiation policy.

## Capabilities

### Modified Capabilities

- `negotiation-protocol`: quote accessor, amount-read guard, bounds and acceptance.
- `storefront-publication`: listing bounds, classes and option combinations.
- `resource-pool-management`: validated capacity-bound hints.
- `settlement-configuration`: servicing declaration and three doors.
- `buyer-orchestration`: optional recurring horizon and pre-approval display.

### New Capabilities

None. The lifecycle codec and its common semantics belong to the foundation change.

## Non-Goals

- Rate settlement, payment/dispute adapters and notice-stop commands: the reconciled
  rate-servicing change, named `spot-deals-through-arkhai-payments` at integration.
- End service, `end_delivery`, buyer end commands and signed end evidence: the
  lifecycle foundation. Unentitled seller withdrawal uses the `exceptional_end(at)`
  dispute filing; unused prepaid service is reversed by its standard ruling, not a compensation enum.
- Delivery admission/window derivation: `unify-compute-delivery-path`; activation
  deadlines: `renewable-compute-lease-deadlines`.
- Discovery and `--class`: `discover-open-ended-compute-listings`.
- Minimum-spend primitives, storefront-local stop scheduling (see design's rejected alternatives),
  backdated payment stops, or extending accepted leases after listing edits.

## Dependencies and gates

- `agreed-evidence-and-early-termination`: codec, authority checks, option identity,
  Alkahest release-model migration and common projections, before wire edits.
- `negotiation-driven-capacity-resize`: reverify its landed multiplier contract
  before implementing the accessor.
- Rate-servicing change: freeze `period`, `reserve_ahead_seconds`, setup pricing and
  the servicing declaration with the accessor's unit contract. Rate materialization
  depends on its adapter, not merely the presence of these terms.
- `converge-ongoing-compute-leases` owns startup/retained-deal execution and evidence;
  spot owns materialization execution/evidence. Neither is a prerequisite to this change's
  archive: sections 1–2 and 3.1 hand off accessor/codec/declaration contracts, and this plan
  qualifies declaration/publication/acceptance only. Consumer gates still precede live offers.
- Registry carrier/filter dependencies gate discovery/activation, not dark terms.

## Impact

`core/src/market_core/schemas.py`, `scripts/`, `kit/resource-pools-contracts`,
`kit/settlement-runtime`, both compute domain models, storefront publication/policy/
negotiation composition and both buyer CLIs. Consume the foundation's Alkahest
migration rather than implementing it twice. Terms affect option identity; accepted
options are immutable and cannot be rewritten from the current listing.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Derived classes/unit-bearing price: architecture vocabulary and negotiation spec.
- Listing bounds/tier resolution: publication spec and architecture companion;
  resource-pool-management spec.
- Servicing doors: settlement-configuration spec and publication architecture.
- Optional horizon/truthful display: buyer-orchestration spec and architecture.
- Codec/authority ownership stays in the foundation's lifecycle contract; no second
  codec is introduced here.
