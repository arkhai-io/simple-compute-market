# Frozen dependency contracts

These are implementation inputs for terms and its consumers, not claims that the
interfaces or rate execution exist. The owner's round-1 review (record 01) settled
the design these contracts rest on; where it amended one, the entry below states the
settled contract, which the round-2 sections of `tasks.md` implement. D-a–D-e of
resize/registry are unchanged.

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
- Carrier: the registry listing's `pricing` object, retained whole and compared
  with the signed body; the family rates the buyer reads are a copy of
  `pricing.rate_structure` and must equal the signed ones. Verified against retained
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
- The `delivery_end` revision is vendored in the mediation contract, but the hosted
  mediation service still runs an older one: a setup-bearing preset publishes only
  where the helper declares `supports_setup_delivery_end` and the servicing
  declaration sets `setup` for its mechanism. Setup-free candidates remain
  independently eligible.
- Bounds remain listing-level. The accepted horizon is the unrounded Agreement
  `duration_seconds`; no maximum term is inserted into an option or its identity.
- Unsupported `settles_through` fails closed through the foundation codec. The
  returned-end compute presets are not relabelled as supported charged presets.

## Servicing handoff

One composition-owned declaration lists, per mechanism, the `settles_through`
treatments the composition has qualified and whether it services setup
(`[settlement.rate_servicing.<mechanism>] treatments = [...]`, `setup = ...`);
absent or empty means no rate servicing. The neutral contract is `RateServicing` in
`kit/settlement-runtime`'s `rate_servicing.py`. Round 1 implemented an earlier form —
an adapter-required revision map, `published`/`proposed` declarations and a
`proposed_lane` identity — which round 2 (section 6) replaces with the treatments
table; spot's materialization gate then checks the option's treatments and `setup`
against the declaration instead of calling `select()`. A refusal keeps the
withdrawn-option/refetch semantics.

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
Both compositions expose `rate_preset_helpers` and `delivery_deadline_for_pool`.
The composition supplies the deadline: that port's value when it gives one, else the
payments clause's configured `delivery_deadline_seconds`; the helper receives the
resolved value through `derive_rate_preset` and needs nothing new.
The structured clause's `recurring` request is absent for once publication;
its payer/payee notices derive the class rather than storing one. Servicing
selection now gates this seam through each composition's `rate_servicing` object;
`RatePresetRequest.servicing` passes the selected declaration to the encoder.

## Acceptance timing handoff

`kit/settlement-runtime/src/market_settlement_runtime/horizon.py` supplies
`RateTermTiming(period_seconds, approval_window_seconds, context)` and the pure
`resolve_horizon` bound/runway resolver. Both storefront compositions expose
`rate_term_projections`, a mechanism-to-callable mapping from the exact selected
option to those timing/capability facts. Spot supplies its installed mechanism's
parser and foundation `TermContext`; neutral terms code never guesses payment
field names or supported partial-period behavior. Missing projections refuse.
Deployed compositions still supply none. A servicing declaration alone cannot
make a recurring option acceptable.

The schema-opaque negotiation runtime calls `resolve_acceptance` after fixing the
acceptance clock and before artifacts/writes. Both domains resolve the original
requested horizon against that exact instant, preserve option/requested wire,
and bind the result only in the Agreement (and bare-metal physical artifacts).
The approval expiry is `floor(accepted_at) + approval_window_seconds`. Foundation
validation enforces the selected lifecycle's term-end treatment. Spot materializes
its absolute end from accepted start plus duration and consumes the same selector;
convergence must not rederive either from current listing edits or new-offer gates.

## Ownership and implementation sequence

Task 2.1 implements the accessor and accepted snapshot retention; the round-2
section removes its reader guard in favour of tests at each money consumer.
Task 2.3 consumes the injected helper in both publication compositions. Task 3.1
implements the neutral declaration and its two terms-owned gates (now qualified
by the committed publication diagnostic). Consumers may
implement against these contracts without this change reaching archive first.
No consumer execution is a prerequisite for recording this handoff; actual
activation remains gated by each consumer's evidence.
