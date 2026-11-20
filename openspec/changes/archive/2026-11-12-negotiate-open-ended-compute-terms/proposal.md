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
  contract. Every consumer that spends, caps, displays, recovers or confirms accepted
  money reads it through the accessor and is tested with a per-period Agreement; no
  static check inventories `amount` reads (D2).
- A signed-acceptance pricing pin binds the agreed multiplier and the digest of the
  publication's `pricing.rate_structure`. Buyers verify the one opening/round/acceptance
  rate identity against the registry's retained seller-signed publication, comparing its
  whole `pricing` object, never a seller-returned database snapshot.
  `Agreement.listing_hash` remains unchanged; its database-listing/publication mismatch
  is an unowned gap (D2b).
- Keep listing-level `max_duration_seconds` and add `available_until_utc`, through
  hints, storefront overrides and configured defaults. For an unnamed recurring
  horizon, at the resolved start, `duration_seconds =
  min(max_duration, available_until - start)` over stated finite bounds, floored to
  whole seconds, not rounded to periods, and with at least one whole period. Reserved
  deals must also satisfy both bounds. A recurring horizon must also leave the runway:
  its term end is no earlier than the latest permitted approval plus
  `delivery_deadline_seconds` plus one period, checked at derivation for the default
  horizon and at acceptance for a buyer's, which is refused with the minimum that
  passes. The negotiation runtime resolves acceptance through a domain hook, and each
  buyer checks the signed horizon against both bounds before approval (D5).
- Publish each compute option's `lifecycle.delivery_deadline_seconds` from the
  composition: the pool port's value when it gives one, else the payments clause's
  configured value; an option with neither carries no term, which the default buyer
  refuses and the seller-side diagnostic names (D3).
- Publish one listing per existing capacity/shape identity with separately priced
  options for its billing/entitlement combinations, derived by one shared per-clause
  step both compute domains call (D9). Omit unbounded recurring candidates without
  suppressing valid reserved ones. In both domains no positive relative maximum means
  no relative limit, retiring bare metal's reserved hold (D5).
- Resolve both compute domains' settlement clauses and listing terms from one shared
  source, adding a pool-level `pricing.settlements` hint (D10).
- Gate publication, acceptance of cached selections and rate-part materialization
  on one composition-owned servicing declaration listing, per mechanism, the qualified
  `settles_through` treatments and whether setup is serviced. Preserve servicing of
  accepted deals even when new offers are disabled (D6).
- Both buyer CLIs show class, unit-bearing price, setup once charge, reserve,
  maximum term, the delivery deadline, entitlements/notices, per-stopper and term-end
  `settles_through` billing treatment and adjudication/retention terms, from numbers
  each mechanism's `present_payment` supplies. Presets default the payee stop and the
  term end to `last_boundary`, mapped to payments `end.partialPeriod: returned`.
  Buyer guarantees rest on authority records and kept signed bytes (D7).
- Each default buyer refusal has its own waiver, with `--allow-unprotected-terms` as
  shorthand for all four; both CLIs accept `--duration-seconds`, VM keeping
  `--duration-hours`, and `bare-metal buy` keeps its reserved 3600-second default (D11).
- An on-demand preset's default premature-stop penalty is the per-period price times a
  storefront setting, 24 by default (D3).
- Drop bare metal's minimum-spend gate. A setup `once` part beside the rate is the
  seller's choice, admitted where the servicing declaration sets `setup`. Sellers may
  refuse churners in negotiation policy (D8).
- Permanent tests at the levels `docs/development/TESTING.md` assigns for every
  behaviour this change adds.
- Promote two principles: compatibility is owed to what a release shipped, and sibling
  domains of one family behave alike (D12).

## Capabilities

### Modified Capabilities

- `negotiation-protocol`: quote accessor and tested money readers, the pricing pin
  over `pricing`, bounds, the acceptance hook and the buyer's horizon check.
- `storefront-publication`: listing bounds, classes and option combinations, the
  deadline's source, the penalty setting, the unified clause source and one
  reserved-bound rule.
- `resource-pool-management`: validated capacity-bound hints and the pool-level
  settlement hint.
- `settlement-configuration`: the servicing declaration of qualified treatments and
  setup, and its three doors.
- `buyer-orchestration`: optional recurring horizon, pre-approval display from the
  mechanism's presenter, per-term waivers and duration flags.
- `deal-lifecycle`: a compute option whose site enforces no delivery deadline carries
  its settlement clause's configured one, rather than none (D3's deadline source).

### New Capabilities

None. The lifecycle codec and its common semantics belong to the foundation change.

## Non-Goals

- Rate settlement, payment/dispute adapters and notice-stop commands: the reconciled
  rate-servicing change, `spot-deals-through-arkhai-payments`.
- End service, `end_delivery`, buyer end commands and signed end evidence: the
  lifecycle foundation. Unentitled seller withdrawal uses the `delivery_end(cause=payee)`
  dispute filing; unused prepaid service is reversed by its standard ruling, not a compensation enum.
- Delivery admission/window derivation: `unify-compute-delivery-path`; the site's
  enforcement of a pool deadline tag: `renewable-compute-lease-deadlines`.
- Discovery and `--class`: `discover-open-ended-compute-listings`.
- An Alkahest purchase in the bare-metal buyer, recorded as an unowned gap.
- An end-to-end run exercising recurring servicing, recorded as a planning gap for this
  change or `spot-deals-through-arkhai-payments`.
- Minimum-spend primitives, storefront-local stop scheduling (see design's rejected alternatives),
  backdated payment stops, or extending accepted leases after listing edits.

## Dependencies and gates

- `agreed-evidence-and-early-termination`: codec, authority checks, option identity,
  Alkahest release-model migration and common projections, before wire edits.
- `negotiation-driven-capacity-resize`: its landed multiplier contract and single
  rate-structure digest.
- `store-registry-listings-as-published`: the retained seller publication and its
  `pricing` object.
- `renewable-compute-lease-deadlines`: supplies the pool port's deadline, which takes
  precedence over the clause's configured value once wired.
- Rate-servicing change: freeze `period`, `reserve_ahead_seconds`, setup pricing and
  the servicing declaration with the accessor's unit contract. Rate materialization
  depends on its adapter, not merely the presence of these terms.
- `converge-ongoing-compute-leases` owns startup/retained-deal execution and evidence;
  spot owns materialization execution/evidence. Neither is a prerequisite to this change's
  archive: sections 1–2 and 3.1 hand off accessor/codec/declaration contracts, and this plan
  qualifies declaration/publication/acceptance only. Consumer gates still precede live offers.
- Registry carrier/filter dependencies gate discovery/activation, not dark terms.

## Impact

`core/src/market_core/schemas.py`, `scripts/` (the amount-read guard's removal),
`kit/resource-pools-contracts`, `kit/settlement-runtime`, `kit/arkhai-payments` (the
compute deadline), both compute domain models, storefront publication/policy/
negotiation composition, both buyer CLIs, the reserved-payment E2E drivers and
`docs/operator-handbook.md` (the bare-metal upgrade step).
Consume the foundation's Alkahest migration rather than implementing it twice. Terms
affect option identity; accepted options are immutable and cannot be rewritten from the
current listing.

This change has two acceptance boundaries. The terms boundary is dark recurring
publication, acceptance and display. The unification boundary changes v0.3.0
bare-metal publication behaviour: a bare-metal pool held for lack of a maximum
duration now publishes reserved options with none, which the operator handbook's
upgrade step covers. v0.3.0 VM configurations and hints keep their meaning.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: derived classes → `docs/development/ARCHITECTURE.md` and
  `openspec/specs/negotiation-protocol/spec.md`.
- D2: unit-bearing price and tested money readers → `docs/development/ARCHITECTURE.md`
  and `openspec/specs/negotiation-protocol/spec.md`; D2a retains resize's monetary
  Agreement carrier and transcript multiplier, with recurring derivation before acceptance.
  D2b's published-rate identity over `pricing`, signed-acceptance pricing pin and
  historical proof verification → `openspec/specs/negotiation-protocol/spec.md` and the
  authority description in `docs/development/ARCHITECTURE.md`.
- D3: shared-codec consumption, the deadline's source and the configurable penalty
  multiple → `openspec/specs/settlement-configuration/spec.md` and
  `openspec/specs/storefront-publication/spec.md`, and the clause fallback into
  `openspec/specs/deal-lifecycle/spec.md`'s two delivery-deadline requirements; codec
  and authority ownership remain there.
- D4: lifecycle placement → `openspec/specs/settlement-configuration/spec.md`,
  referencing the foundation-owned `openspec/specs/deal-lifecycle/spec.md`.
- D5: listing bounds, tier resolution, the accepted horizon, the acceptance hook, the
  floored default, the buyer's horizon check and the reserved-bound rule →
  `openspec/specs/negotiation-protocol/spec.md`,
  `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/storefront-publication/architecture.md`,
  `openspec/specs/resource-pool-management/spec.md` and the bare-metal upgrade step in
  `docs/operator-handbook.md`; the buyer check's seams (core's per-listing acceptance
  validator and the bounds a resumed run keeps) →
  `openspec/specs/buyer-orchestration/architecture.md`.
- D6: the servicing declaration and its doors →
  `openspec/specs/settlement-configuration/spec.md` and
  `openspec/specs/storefront-publication/architecture.md`.
- D7: optional horizon, truthful display, the mechanism's presenter and the default
  buyer's policy → `openspec/specs/buyer-orchestration/spec.md`,
  `openspec/specs/buyer-orchestration/architecture.md` and
  `openspec/specs/settlement-configuration/spec.md`.
- D8: setup pricing versus seller refusal policy →
  `openspec/specs/buyer-orchestration/spec.md`,
  `openspec/specs/buyer-orchestration/architecture.md` and
  `openspec/specs/settlement-configuration/spec.md`.
- D9: recurring publication and the shared per-clause step (`RatePresetHelper`) →
  `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/storefront-publication/architecture.md` and
  `openspec/specs/settlement-configuration/spec.md`.
- D10: the unified clause source → `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/storefront-publication/architecture.md` and
  `openspec/specs/resource-pool-management/spec.md`.
- D11: per-term waivers and duration flags →
  `openspec/specs/buyer-orchestration/spec.md`.
- D12: compatibility owed to releases → `docs/development/RELEASING.md`, under
  "Versioning policy"; sibling domains alike → `docs/development/ARCHITECTURE.md`,
  under "Family kits".

These are post-review destinations, not promotion of unimplemented behavior.
