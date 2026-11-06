# Frozen dependency contracts

These are implementation inputs for terms and its consumers, not claims that the
interfaces or rate execution exist. D2a is decided by webapp owner 2026-11-06,
pending maintainer review. D-a–D-e of resize/registry are unchanged.

## Price and accepted evidence

- Negotiation scalar: nonnegative integer basis points; 10,000 is 1x. The
  multiplier stays in the transcript. It is not the Agreement payment amount.
- Before acceptance, evaluate the complete selected-asset shape rate as an exact
  rational, multiply by the scalar and duration, then round upward once. Refuse
  a result above uint256. Use the Agreement duration for prepaid and one selected
  option period for recurring. Flat/absolute negotiation keeps its existing path.
- `agreed_price(agreement, listing)` returns the accepted monetary amount and
  `total` or `per_period`, plus the selected period for presentation. It must not
  multiply the already accepted amount by duration or by the multiplier again.
  The billing-kind interpretation is of the accepted option, not a current offer.
- Carrier: top-level registry `rate_structure`, verified against retained
  `publisher_publication.body_base64` and its complete authenticated request.
  Verify the historical signature at its signed timestamp, seller trust, listing
  identity and `listing.publish` context. A legacy row without proof fails closed
  for multiplier pricing. A registry signature alone is not seller evidence.
- At opening, resize D-e pins the rate-structure digest; changed/missing pins on
  continuation or acceptance refuse as `rate_structure_changed_reopen`. This
  does not authorize replacing accepted evidence after commitment.
- Keep the verified publication, selected option, transcript multiplier and exact
  signed acceptance/Agreement bytes together for recovery and buyer mandate
  validation. The VM buyer currently retains only a selected listing-field subset;
  preserving and validating the proof with that snapshot is part of task 2.1,
  before migrating recovery/mandate readers. It is not claimed implemented here.

## Shared codec and identity

`kit/deal-lifecycle` alone interprets `lifecycle`. Keep its `adjudication`, optional
`early_termination`, `delivery_deadline_seconds` and reserved `bond` shapes. Core
and registry carry these rights beside `price` and `settlement`; mechanism params
never duplicate them. Option identity includes the exact lifecycle. An Alkahest
option has no lifecycle adapter: absence is valid, presence is refused. Carrying
rights structurally does not prove a mechanism can service them.

## Rate-helper handoff

The injected helper consumes resolved inputs, not seller configuration files:
selected quote/unit and asset, `period`, `reserve_ahead_seconds`, optional setup
amount, listing bounds, pool delivery deadline, adjudication, early-termination
rights, and the composition's servicing declaration. It returns a canonical
candidate option or a named derivation refusal. Terms resolves preset choices,
defaults, bounds and diagnostics; spot owns hosted parameter encoding and the
helper implementation. Missing helper omits recurring candidates, without
reconstructing mechanism params in domain publication. Generic qualification
injects a helper; live rate support is not inferred from a successful fixture.

- `period` is a positive fixed-unit ISO duration; `reserve_ahead_seconds` is a
  positive integer. They appear together or neither, flat in `settlement` beside
  `schema`. The payment adapter alone translates reserve seconds to `reserveAhead`.
- `approval_window` governs approval expiry, not adjudication or payout holds.
- Additional `setup_amount` is a positive canonical minor-unit string in the
  option asset; omission means no setup part. It is not part of the recurring
  quote. VM may resolve zero to omission; bare-metal has no invented setup price.
- Setup-bearing presets wait for foundation 12.1's vendored delivery_end revision
  and both signature vectors. Setup-free candidates remain independently eligible.
- Bounds remain listing-level. The accepted horizon is the unrounded Agreement
  `duration_seconds`; no maximum term is inserted into an option or its identity.
- Unsupported `settles_through` fails closed through the foundation codec. The
  returned-end compute presets are not relabelled as supported charged presets.

## Servicing handoff

One composition-owned declaration identifies the serviced mechanism and contract
revision and whether it is published or proposed. A proposed declaration requires
an explicitly opted-in test lane; it is not production readiness. The neutral
contract belongs in `kit/settlement-runtime` (task 3.1). Spot layers exact payments
service identity and `livemode=false` checks on its lane materialization path.

Publication, cached-option acceptance and materialization all consume that same
contract, never an option-local assertion. Absence omits recurring publication and
refuses acceptance before persistence with withdrawn-option/refetch semantics.
Spot owns the materialization gate; convergence owns startup/continuation and
ensures disabling new offers does not strand accepted work. This change's fixtures
qualify publication/acceptance only. No deployed recurring offers are enabled by
this document, the declaration, or an injected proposed helper.

The publication interface now lives in
`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`:
`RatePresetHelper.pricing(clause, authorities)` returns `RatePresetPricing`
(unit-bearing reference `quote`, parsed period, approval window, adjudication,
`TermContext` and the vendored setup capability). `build(RatePresetRequest)`
returns a canonical option or `RatePresetRefusal`. The common derivation checks
the authority against the composition's offered advertisement, derives the
penalty recommendation/runway and validates lifecycle capabilities before build.
It then refuses changed mechanism, asset, period, reserve or lifecycle bytes.
Both compositions expose `rate_preset_helpers` and `delivery_deadline_for_pool`;
the latter reads site/pool facts, defaulting to no enforced deadline until the
effective pool-facts port is wired. A raw clause value cannot stand in for it.
The structured clause's `recurring` request is absent for once publication;
its payer/payee notices derive the class rather than storing one. Servicing
selection/declaration inputs still belong to task 3.1 and must gate this seam.

## Ownership and implementation sequence

Task 2.1 implements the accessor, accepted snapshot retention and reader guard.
Task 2.3 consumes the injected helper in both publication compositions. Task 3.1
implements the neutral declaration and its two terms-owned gates. Consumers may
implement against these contracts without this change reaching archive first.
No consumer execution is a prerequisite for recording this handoff; actual
activation remains gated by each consumer's evidence.
