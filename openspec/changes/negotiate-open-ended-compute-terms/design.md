# Design

## Context and authority

This design-stage change reconciles compute terms onto
`agreed-evidence-and-early-termination`. Its vocabulary and codec win. Design for
an adversarial counterparty and make the reference implementation cooperative.
The buyer can rely on authority records and kept signed bytes, not seller uptime.
This change owns compute terms and presentation, not authority operations.

Current `SettlementOption.params` is a dictionary, hashed with mechanism, asset and
rates; the selected option reaches Agreement verbatim. VM substitutes durations in
negotiation/resume; bare metal requires a positive lease bound. Alkahest's option
builder uses `params.accepted_escrow`; typed `EscrowTerms` describes obligation
params, not option params. Recheck these seams after dependencies land.

## Decisions

### D1. Classes are derived presets, never stored

| Selected option billing | Payer entitlement | Payee entitlement | Display |
|---|---|---|---|
| prepaid once | — | absent | reserved |
| per period (`period` present) | present | absent | on-demand |
| per period | present | present | spot |
| prepaid existing Alkahest splitter | — | release condition permits interruption | prepaid interruptible |

A setup once charge beside a rate does not make it prepaid. One listing can offer
several combinations at different rates over its existing pool/shape identity;
options add no publication-derivation dimension or duplicated capacity. `--class`
is discovery sugar, not a wire field.

The existing splitter stays seller-trusted with its current service terms. The
foundation removes `listing_resource.interruptible` and `settlement_model`,
migrates flags to `release_models`, and retains bare metal's unsupported-splitter
refusal. Read the accepted release condition for display; do not invent lifecycle
terms for a mechanism with no lifecycle adapter.

### D2. Quote once with its unit; guard every read

`Agreement.amount` follows `negotiation-driven-capacity-resize`: basis points over
a resolvable advertised rate structure, otherwise an absolute amount. Billing kind
changes the evaluation duration: Agreement duration for prepaid, option period for
recurring. Retain upward rounding and the asset's amount-range refusal.

Core's `agreed_price(agreement, listing)` returns price and unit `total` or
`per_period` (with the actual period for presentation), never an unlabelled integer.
Both policies/reference quotes, buyer caps/display, VM amount checks, mandate
derivation and buyer mandate checks use it. Additional setup pricing is explicit,
not hidden in the recurring quote. At 2,500,000 USD/6 per hour and 10,000 bps,
two-hour prepaid is 5,000,000 total; PT15M is 625,000 per period; PT1M is 41,667.
Recovery and buyer mandate checks use the signed-acceptance-bound rate structure and selected option, never a current or registry-cached listing. `negotiation-driven-capacity-resize` task 2.1a's carrier decision gates this accessor: retain the bound structure or its verifiable digest in accepted evidence before approval.

A fail-closed repository check refuses direct `Agreement.amount` reads outside the
accessor and declared raw negotiation hooks. Cover actual attribute/mapping reads
and aliases/wrappers; an unclassified reader fails rather than escaping detection.
Model declaration/serialization is not price interpretation. Each hook allowlist
entry records why it negotiates the scalar instead of spending it.
Recommendation: an AST-based guard using the existing architecture-check pattern,
with positive/negative fixtures in its owning script tests; use the smallest
implementation that rejects every repository reader found during migration.

### D3. One shared codec, no interruption object

Keep the foundation's exact shapes and names:

- `early_termination = {version, entitlements, max_term_seconds, settles_through, premature_stop_penalty?}`;
  its top-level `settles_through` is the sole term-end treatment carrier (no mechanism-specific duplicate), separate from
  entitlements keyed by `payer`/`payee`, each `{notice_seconds, settles_through}`.
  Foundation D5 owns the `settles_through` mapping: `started_period` ↔ charged,
  `last_boundary` ↔ returned, `stop` ↔ prorated. Seller presets offer payer charged and
  payee returned; the buyer's default acceptance policy refuses a payee entitlement
  or term end that is not returned (the buyer benefits, so the buyer enforces it in
  negotiation), and a buyer may loosen it. Until the vendored contract expresses
  returned, interim rate options explicitly offer charged treatment, which default buyers refuse. Publication and acceptance fail closed on any
  unsupported treatment. `exposure_seconds` and `stop+exposure` are retired.
- `adjudication = {version, dispute, dispute_window_seconds, case_hold_max_seconds}`;
  `dispute = {interface, origin, account, record_key, params}`.
- `premature_stop_penalty` is a nonnegative integer amount in the option asset's minor units, encoded as a canonical decimal string; absent/zero means none. It applies to an unentitled seller end, including a spot emergency without notice, not an entitled notice stop. Recommendation: on-demand presets default to 24 periods' price (calculated through the agreed-price accessor), and buyer default acceptance refuses on-demand without a positive penalty because the buyer benefits and enforces it, like partialPeriod. Expose seller override and explicit buyer opt-out; never silently downgrade the default.
- `bond` stays reserved where the mechanism cannot hold a seller-funded stake.

A payee entitlement means the seller may interrupt; the payment authority enforces
its notice as a pending stop on that stop authority, not a local schedule.
On-demand has no payee stop entry. The mandate therefore does not enforce that the seller
won't preempt; that is enforced by the penalty and a buyer's case over held money, not by the mandate.
The seller's own exit is `exceptional_end(at)`, a dispute filing the seller half journals with
the end and files with the dispute authority; the seller sends no stop or reverse of its own.
Arkhai mediation rules a payee-filed request at least as strong as the standard one
mechanically: stop rate parts now returned (always returned on on-demand), reverse earnings
since at and each once part's unserved time share, setup all if undelivered and none after
activation, then reverse min(premature_stop_penalty, earned amounts still held) across parts in mandate order. Bond award stays reserved for hosted bonds. A buyer contesting the account files a case; mediation
triages every other case, including buyer_end, for a person. There is no compensation enum.
Entitled rate stops follow the committed per-stopper `settles_through`, computed by the
payment authority, not a later storefront refund or promise to prorate every end.

Hosted once options carry adjudication but no early_termination: no part is
stoppable. Recurring presets carry payer and optionally payee entitlement. Buyer
notice is offered/priced and may be zero; it is the only paid stop tail.
Polling/watchdog/teardown budgets are seller recommendations, not another term.
Adjudication must use an accepted authority and satisfy its advertised minimums.
Unsupported/malformed terms and unknown versions fail closed in the shared codec.

Resolve seller preferences through override > pool hint > configured default,
keyed per offered preset like its rate. These are seller choices, not a protocol
requirement to price identically. Recommendation: shipped recurring presets have
a payer entitlement and setup once part; spot adds a payee entitlement. Omission
never grants the payee an implicit entitlement. The foundation owns validation and
identity inclusion; do not create a second hash rule or require early_termination
on every compute option. Terms injects a preset-helper interface: selected quote/unit,
period/reserve, setup, bounds, adjudication and early-termination declarations in;
canonical candidate params or a named derivation refusal out. Spot supplies the
hosted helper; generic publication tests use injected helpers. Missing helper omits
the recurring candidate, never reconstructs mechanism params. Neither archive waits
for the other's execution.

### D4. The terms are option params

`early_termination` and `adjudication` are objects in the selected option's `params`, and so in the Agreement bytes and the option ID. This follows the foundation's rule that terms take the form `mechanism { fields }` with the payment mechanism primary: what a deal may end by and who adjudicates it are terms of the payment the option offers, not fields beside it. Beside `params` would add typed fields to the shared `SettlementOption` wire that every mechanism and registry must carry, for terms only some mechanisms can enforce.

The codec reads both keys by the same names and shapes whatever the mechanism, and must not branch on the mechanism ID or decode Alkahest arbiter demand trees to read them. A mechanism adapter separately refuses terms it cannot enforce: carrying the keys is not permission to advertise an unsupported Alkahest lifecycle promise. `placement-probe.md` records that the current shared carrier and Alkahest's option builders already keep both objects and that changing them changes the option ID; task 1.2 runs the full check once the foundation's codec exists, as a regression test rather than a decision gate.

### D5. Two listing bounds compose at the agreed start

`max_duration_seconds` is the longest deal from its start; `available_until_utc` is
the last possible lease end. Both are listing capacity facts, not option copies or
`listing_resource` fields. Resolve through override > pool hint > configured
default per offering mode. Nonpositive/unset relative bound means no relative
limit; a stated absolute bound is timezone-aware UTC. Malformed bounds hold
derivation with a diagnostic, not a guessed default.

At resolved `start_utc`, let `B = min(positive max_duration_seconds,
available_until_utc - start_utc)` over stated bounds. Default recurring selection
binds `duration_seconds = max_term_seconds = B`.
If one bound is absent use the other. Require at least one whole period, but do not
round the horizon. Bind an explicit shorter buyer horizon unchanged, show the
effective horizon before signature, and refuse a longer, expired or sub-period
selection. Every reserved duration must fit both bounds.

Rate billing starts at activation, potentially later than the Agreement start,
while the payments end is absolute: horizon rounding cannot align that end to a
billing boundary. Foundation D5 therefore gives the term end its own
`settles_through`, mapped to the rate part's `end.partialPeriod` with the same
values as stop authorities. Compute presets use `last_boundary` (returned), so
billing never runs past the agreed maximum. Publication and acceptance fail
closed until that treatment is vendored. Interim recommendation: publish rate
options with an absolute end and a charged final partial period, disclosed in
the option as term-end `started_period`, not as the returned preset. Exhaustion
needs no separate rule: reserve-ahead places it on a period boundary.

Recurring start_utc must resolve to whole-second precision before the final signature;
refuse a fractional rate start rather than round signed bytes. Preserve once-only
fractional handling. The selected option's max term and Agreement duration must agree before signature
and commitment. Adopted recommendation, which the owner may revise: resolve start
and effective horizon before the seller's signed acceptance, which carries the final
option and its canonical ID. The buyer verifies that ID and accepts only if the
option equals an advertised option except for max_term_seconds (and the equal
Agreement duration_seconds), which must not exceed the advertised bound. Only the
canonical ID changes as a consequence of that refinement; every other option field
stays equal. Preserve the advertised-to-final option correlation, never mutate a
cached option or rewrite identity after acceptance. The negotiation-protocol delta
specifies this bounded refinement.

An unbounded recurring candidate yields no option and a derivation close reason,
not a hold merely for being unbounded; valid reserved candidates remain. Bare
metal's existing positive-bound rule for reserved candidates remains. A later
listing-date edit never extends an accepted lease. The shared delivery change
uses accepted start plus duration in both domains, not `now`. Here remove VM's
round-zero missing-reserved-duration fallback; delivery owns its resume fallbacks.

### D6. Three doors read one servicing declaration

Composition, not a listing or buyer, declares rate servicing and its contract:
deployed published revision, or `proposed` only in an explicitly opted-in test
lane. No additional minimum-spend primitive gates it.

1. Publication omits recurring candidates if servicing is undeclared, using existing
   no-settlement-option diagnostics if none remain.
2. Acceptance refuses cached recurring selections when servicing is now undeclared,
   using the withdrawn-option/refetch outcome before persisting acceptance.
3. Materialization refuses to derive a rate mandate without the declaration, even
   across an acceptance/restart gap.

Startup additionally refuses to strand accepted rate deals without their
continuation. Disabling offers never disables accepted-deal servicing.
`converge-ongoing-compute-leases` owns startup/continuation wiring; the rate adapter
owns materialization. This change supplies the common declaration contract and
publication/acceptance gates. This plan qualifies those two gates using injected declarations;
spot owns materialization execution/evidence and convergence owns startup/continuation
execution/evidence. Neither consumer's completion gates this change's archive. Rate offers
remain disabled in deployed compositions until their consumer gates pass.

### D7. Display what the authority can enforce

Both CLIs show class, recurring charge/period or total, separate setup once charge,
initial reserve (not spend), maximum end/horizon, payer/payee entitlements, notice,
per-stopper and term-end `settles_through` treatment, premature-stop penalty amount/asset and capped remedy, dispute authority/window/
case-hold cap and evidence retention. Values come from the selected option, not a stored class. Asking rate keeps its stated unit.

Explain rate start as a journaled effect after lease activation, distinct from buyer
credential disclosure; explain each stopper's started-period charge/return/proration,
the one priced notice, authority-hosted pending stops and adjudication for
unentitled loss of service. Reserve-ahead is not a dishonest-seller billing cap.
Holds last through stop plus dispute window and accepted case extensions. Keep
signed evidence through at least the window after the latest delivery end, last
payout or case close. Sellers file exceptional_end for failed/non-started delivery;
the buyer's stop/case is its backstop. Normal buyer end submits payment-authority stop then a hint: nonzero notice keeps
service until the effective stop is watched. `end_delivery` means end now regardless;
it has no at and the storefront records/signs its own receipt. The storefront cannot stop
billing for the buyer: the buyer half stops at the payment authority first and, if it is
unreachable, journals the stop and retries under one key while billing runs. The buyer may
also file buyer_end(at), human-triaged with kept evidence, preserving notice/treatment and
netting recorded stops. Setup ends
at activation, pays out one dispute window later and is fully returned for an
undelivered deal but not after delivery.

### D8. Churn is seller pricing/policy, not a protocol gate

Neither domain requires minimum spend. Presets default to an honestly named setup
once charge beside the rate. Sellers may price differently or refuse churners,
including by principal blacklist, without claiming resistance to identity rotation.
No new minimum-spend request goes to payments. This change displays setup pricing;
the rate change derives it.

## Rejected alternatives

- Stored class: it can disagree with selected terms.
- `interruption {seller_may_interrupt, notice_seconds, compensation}`: duplicates the shared codec.
- Terms as typed fields beside `params`: widens the shared option wire for terms only some mechanisms enforce, against the payment-mechanism-primary rule (D4).
- Payee notice entry on on-demand: grants the seller a priced reclaim. On-demand carries no seller stop entry, so won't-preempt is enforced by remedy, a buyer case and the bond, and the seller's exit is the mechanically ruled exceptional_end filing.
- Bare-metal minimum spend/new payments primitive: churn is seller pricing/refusal policy.
- Rejecting setup once because it is not minimum spend: name the additive fee honestly.
- Banning principal-blacklist policy: goodwill is not a decentralized protocol guarantee.
- Billing horizon/vouch or payee-advanced horizon: a dishonest seller can advance it forever.
- Backdated/effective-time payee stops: stop now plus held-money reversal covers correction.
- Storefront-local notice scheduling: it dies with the storefront.
- Listing/site/registry copies of an option policy: duplicate truth and cross authority boundaries.
- Early_termination on every option: once/unsupported mechanisms cannot bind it.
- One bound only or a second offer-end date: relative and absolute capacity bounds suffice.
- One listing per class: existing capacity/shape identity can carry multiple options.
- New Agreement rate field, zero duration or hourly reinterpretation: preserve scalar semantics and finite lease window.
- Publication-only/materialization-only gates: either permits an unserviceable accepted deal.
- Reserve-ahead as worst-case buyer-loss cap: guarantees require authority actions, holds and evidence.
- Prorating every buyer end/prepaid provisioning time here: changes pricing outside this reconciliation.

## Dependency gates and sequence

Foundation codec, authority validation and release-model migration precede wire edits. Reverify resize before accessor migration. Freeze recurring
`period`, `reserve_ahead_seconds`, setup pricing and servicing declaration with the
rate change. Implement D5's adopted bounded final-option refinement in acceptance.
Sections 1–2's accessor/codec and 3.1's declaration are section-level handoffs to spot.
This change can archive with its own declaration/publication/acceptance/display evidence;
spot's materialization and convergence's continuation evidence are not prerequisites.
Publication and buyers can then proceed while adapter/continuation are prepared;
rate offers remain dark until all three doors can succeed. Discovery and activation
also require the registry carrier chain; hosted deployment gates activation, not
implementation against an in-lane double. Site lapse choices are seller policy,
not buyer protocol guarantees.

## Goal 8 review triage

No standalone review of this terms change was supplied this round. Applied the terms-facing findings from spot external F1/F9/F10/F12 and convergence external F6: foundation-owned `settles_through` values and fail-closed expressibility, one notice without exposure, unrounded horizons with explicit term-end billing treatment, accepted pricing evidence, truthful stop-and-hint and setup display. Rejected: a seller-only started-period refund, because only a committed payment term survives an adversarial seller and independent dispute execution. The focused cross-change re-check adopts D5's owner-revisable recommendation as the bounded final-option refinement, with an explicit negotiation-protocol delta rather than an unresolved identity gate.

Second-review triage applies foundation 18 F4/F13/F14 and spot 03 F2: one term-end carrier,
terms-owned default buyer policy, all interim charged term ends refused by default, and no
terms-to-materialization/startup closeout cycle. The final owner decision makes the seller's
exceptional_end a dispute filing, mechanically ruled only when at least the standard
self-penalty, and keeps buyer_end a buyer-filed case ruled by a person.
The focused cross-change re-check leaves this change ready for implementation,
subject to the recorded dependency and section-level gates.

## Design validation

On 2026-10-29, pinned OpenSpec 1.14.0 and installed `openspec` strict validation
passed without long-requirement warnings, and
`make check-change CHANGE=negotiate-open-ended-compute-terms` passed, including
comment hygiene, agent skills, citations, task structure and the current change
index. `placement-probe.md` records the partial carriage experiment; the full codec check
is task 1.2. No runtime implementation, new tests, deployment or
permanent-document promotion was performed; packaging and runtime suites are future
implementation gates, not claimed evidence here.

## Design promotion record

Destinations are planned, not claims of implemented behavior.

| Accepted decision | Permanent location |
|---|---|
| D1, D2 classes and quote unit | `docs/development/ARCHITECTURE.md`; `openspec/specs/negotiation-protocol/spec.md` |
| D3 penalty preset default (24 periods) and buyer acceptance recommendations; D4 placement result | `openspec/specs/settlement-configuration/spec.md`; foundation-owned lifecycle contract |
| D5 bounded final-option refinement, listing bounds and omission | `openspec/specs/negotiation-protocol/spec.md`; `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/resource-pool-management/spec.md` |
| D6 servicing doors | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/storefront-publication/architecture.md` |
| D7, D8 display and seller-policy distinction | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md` |
| Goal/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
