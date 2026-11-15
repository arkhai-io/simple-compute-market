# Design

## Context

The lifecycle foundation, [`agreed-evidence-and-early-termination`](../archive/2026-11-03-agreed-evidence-and-early-termination/),
is the frame: the protocol ends at commitment, and everything after it is
authority records and the signed bytes each party keeps. The terms a deal
carries — `early_termination {version, entitlements, settles_through,
premature_stop_penalty?}` and `adjudication` — live under the
selected option's `lifecycle`, beside its `price` and `settlement` (foundation D5,
"The option's shape"; terms D4). Payment derivation consumes that shared codec; it
keeps no mechanism-specific copy of the terms.

`kit/arkhai-payments` vendors the published per-part contract
(`kit/arkhai-payments/schema/SOURCE.md`; there is no unpublished candidate): per-part
authorities with no mandate-level ones, `maxHoldExtension`, `pendingStop`, and stop
entries and part ends carrying `partialPeriod` — `charged`, `returned`, `prorated`, or
`chosen` on a stop entry. Every treatment the terms name is expressible, and the code
assumes that contract. What limits an offer is hosted execution, not the contract: a
composition offers only the treatments its servicing declaration lists, declared after
hosted qualification (D7). The foundation vendored the contract once for both changes.

Both compute domains are in scope. API credits stays on `once` parts. The adapter
is mechanism-owned and stateless; the caller's journal and continuation state live
in `kit/deal-servicing`, implemented by
[`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/).

## Decisions

### D1. Rate options and presets use the common terms and the price accessor

The settlement schema stays `arkhai.payments.v1`. A rate option states `period`
(a positive fixed-unit ISO duration) and `reserve_ahead_seconds` (a positive
integer) together, or neither, flat under `settlement` beside the schema; the
adapter converts the seconds to the wire's `reserveAhead`. Approval expiry is
`approval_window`; payout protection comes from `adjudication` and never from
approval expiry. A rate option carries valid `early_termination` and `adjudication`
terms and a finite maximum term. The option carries one `asset`, in `price`; the
hosted parameters do not repeat it, and the mandate reads the option's.

Prices come from the agreed-price accessor
[`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)
defines. For a rate option its value is the upward-rounded minor-unit charge for
one period; for a once-only option it is the term price. The kit never reads the
negotiated scalar directly and never reinterprets a basis-point multiplier. Both
sides derive the same parts from the selected immutable option and the rate
structure bound by the signed acceptance; recovery's accessor is never fed today's
listing or a registry cache. Rate derivation reads the accepted per-period money
through `agreed_price` over the monetary `Agreement.amount`, which signed acceptance
binds; no separate accepted-rate carrier is needed.

The rate parameters are the paired `period` and `reserve_ahead_seconds`, an optional
`setup_amount`, a finite term, and the asset in `price`. Acceptance horizon resolution
and mandate derivation share one runway rule, `minimum_rate_duration_seconds`,
measured from `max(approval expiry, start)`: the term leaves the delivery deadline
and one whole period after the later of the two. The public discovery projection is
`arkhai_payments.billing_kind = total | per_period` (setup beside a rate stays
`per_period`), and `arkhai_payments.period` reads absent as the typed missing value
`None` under the existing DSL missing-value rule. The installed billing projection
refuses an unpaired rate rather than label it a total.

**Setup.** An optional `setup_amount`, a positive integer minor-unit string in the
option's asset, adds a `once` part beside the rate; omission means no setup part.
It is an additional charge, not `max(setup, usage)`, visible before approval and
bound into the option ID. A preset populates it from an explicitly configured setup
price and refuses an incomplete configuration rather than inventing an amount. A
setup amount is the seller's choice in both domains, as storefront-publication's
"Recurring publication checks servicing" says; there is no reason for it to differ
between them, and the bare-metal example configuration and operator documentation
recommend pricing setup for hosts, since provisioning a host is the cost churn
imposes. Churn beyond the setup charge is the seller's to price differently or to
refuse through its negotiation policy; neither domain has a required minimum spend.

Setup is owed from approval because commitment triggers provisioning. A payment stop alone does not reverse it, and lawful preemption after delivery leaves it earned. A qualified delivery_end reverses setup iff delivered=false, for either cause, and keeps it iff true; site activation is not that fact. "For either cause" generalizes the filer, not the ground: setup returns only when the seller never delivered — by the seller's own filing, by its signature on the buyer's claim, or by a person ruling delivered=false on the buyer's evidence — and a buyer's stop, with or without a claim the seller does not sign, keeps it with the seller. The buyer is told before approval that the setup charge is kept if it stops and returns only when the seller never delivered, in those three ways. Parties file or concur through the dispute adapter, with no seller direct payment correction. A lawful controlling end keeps its attribution rather than becoming seller fault, but the claim's delivered value still governs setup.

The setup part remains an ordinary once part. Encode its end at Agreement start so mediation recognizes it (once end at or before Agreement start); payments clamps an end at/before approval to approval without changing mandate bytes, so its effective end/payout anchor is max(Agreement start, approval). No activation-anchored end or payments wire revision is required. The foundation vendored `delivery_end`, its signed payload and concurrence mapping and both signature vectors, so setup's remedy exists; what gates a setup-bearing preset is the composition's servicing declaration, whose `setup` flag says the composition services a setup charge (D7). `supports_setup_delivery_end` stays the mechanism's capability, true for this helper. Delivery is the signed claim's delivered fact, not activation or a unilateral flag.

| Preset | Parts | Entitlements |
|---|---|---|
| On-demand | setup `once` when the seller prices it + time rate | payer `{notice_seconds: 0, settles_through: started_period}`; no seller stop entry |
| Spot | setup `once` when the seller prices it + time rate | payer `{notice_seconds: 0, settles_through: started_period}`; payee with its priced notice |
| Reserved | `once` for the committed term | existing `once` semantics |

Every preset also carries `lifecycle.delivery_deadline_seconds`, the pool's value the
site enforces (terms D3; renewable D3); the preset helper takes it as an input beside
adjudication and emits no compute option without it.

The shipped presets price the payer's notice at zero: a buyer who stops is charged
to the started period and nothing after, and a seller who wants a payer tail
prices it as a number the buyer sees before accepting. Both recurring presets carry
the foundation's `early_termination.premature_stop_penalty`; the injected preset
helper encodes only the penalty the terms change resolves, from its preset default
and the seller's override. An entitled notice stop pays none; an emergency without
notice files `delivery_end` and pays the capped penalty after the refunds. Buyer
acceptance and display of the penalty are the terms change's.

No class flag is persisted or used for dispatch. One pool may publish on-demand and
spot at different rates.

**Composition defaults.** Both compute compositions install the payments preset
helper and its timing projection by default, through one payments-kit function,
`payments_rate_wiring`, which both call. They stay dark until the composition
declares rate servicing: publication, acceptance and materialization each refuse a
rate option whose treatments the declaration does not list. Each composition
constructs its payments seller stage with the same declaration (`rate_servicing=`),
so materialization admits exactly what publication and acceptance admit. The helper's
`pricing()` returns the clause's own `delivery_deadline_seconds` through
`RatePresetPricing`, which the pool's effective deadline overrides, and `pricing()` and
`build()` convert the clause's rate to minor units through one conversion that refuses
a rate finer than the asset's precision.

### D2. Exact per-part mandate derivation

For each rate part the adapter derives `amount`, `asset`, `period`, `reserveAhead`,
the end instant `start_utc + duration_seconds` with its own `partialPeriod`,
`hold = {afterStop: dispute_window}` and `maxHoldExtension = case_hold_max_seconds`.
The accepted `duration_seconds` is the deal's horizon; the listing bounds
already limit that term to `min(max_duration, available_until − start)`, and a
late start never extends it. The terms runtime resolves a whole-second Agreement
start before the rate signature, because the payment wire is integer-second, and
materialization enforces the same backstop; publication validates the supported
precision policy, since it has no Agreement start yet. Signed Agreement bytes are
preserved: a fractional rate start is refused, never rounded up past a capacity
bound. Existing once-only fractional timestamp handling is unchanged.

The term end has its own `partialPeriod` payment term, independent of the stoppers'
entries. Compute presets use `returned` at that immutable end, so a late start
cannot bill a period beyond the agreed maximum: with S = 10, P = 60 and end = 120
the part charges [10, 70), returns the incomplete [70, 130) period, and delivery
still ends at 120. Maximum terms are not rounded down and the absolute end does
not move. Exhaustion needs no separate partial-period policy: `fundedThrough` is a
period boundary under reserve-ahead.

`end.partialPeriod` is derived exclusively from `early_termination.settles_through`
through the foundation codec — `started_period` ↔ `charged`, `last_boundary` ↔
`returned`, `stop` ↔ `prorated` — with no second end-treatment option parameter.
The preset is `last_boundary`. A composition may offer a term end only under a
treatment its servicing declaration lists (D7); publication and acceptance refuse
any other, and SCM implements no compensating refund.

The foundation owns per-part authority derivation from the common codec. This
change adds the rate-specific `start` permission, period, reservation and end
fields. `start` is payee-only. Seller stop entries exist only for accepted
entitlements: on-demand has none, spot has its priced notice entry. Stop entries
carry the entitled party's `notice_seconds` and the `partialPeriod` mapped from its
`settles_through` (D5). An exceptional end grants no seller stop entry or implicit
payment privilege: the seller files a dispute and mediation acts under its own
entry; there is no additional seller restitution entry and no multiple-entry
dependency. Every rate stop entry and rate end carries an explicit `partialPeriod`;
the published schema also requires `partialPeriod` on every part `end`, so `once` and
setup ends carry the foundation's inert `returned`, which prices nothing. The dispute
authority's rate stop entry is `{account, notice: PT0S, partialPeriod: chosen}`,
under which a stop carries its own charged, returned or prorated treatment.
Only the dispute authority extends and lifts holds. Reverse permissions remain the
payee's and the dispute authority's. Setup uses the foundation's `once` permissions
and its own encoded end at Agreement start, effectively clamped to approval if later, without rate start
or period arithmetic. Parts are ordered
deterministically: setup when present, then rate.

There is one notice per entitled party, the accepted entitlement's `notice_seconds`.
The codec has no `exposure_seconds` or `stop+exposure` value. Seller polling,
watchdog and teardown budgets are operational recommendations, not a payment term
or a hidden tail. Reserve-ahead funds service until exhaustion; it does not replace
the priced payer notice, since unearned reservations return on a stop.

The buyer re-derives and checks every part, their order, authorities, notices,
holds, end, cap, asset and amount before approval. A changed listing or
configuration cannot alter an accepted mandate.

### D3. External contract context; one vendoring owner

The published contract has per-part authorities `{stop: [{account, notice,
partialPeriod}], reverse, extend, start}`, with `start` on rate parts, and expresses
every treatment: stop entries carry `partialPeriod` ∈ `charged | returned | prorated
| chosen`, every part `end` requires one, and pending and final stop records carry
the treatment applied. It also carries `maxHoldExtension`, an optional per-part
`end`, `{afterStop: d}` holds, `start` and `stop` with an optional part, `stop` with
an optional `at`, and `extend`/`lift`. An entitled stop
takes effect at `max(at ?? now, now + senderNotice)` at authority receipt and is
never backdated. There is no implicit role-based or buyer-favourable stop
privilege, no payee waiver of payer notice, and no payer early-release waiver: each
stop is authorized by an explicit mandate entry, and reverse uses the existing
reverse authority. The earliest pending stop wins and cannot be withdrawn. The
adapter sends explicit part IDs even where a whole-transaction shorthand exists.

The seller's emergency exit, a spot hardware failure included, is the journaled
`delivery_end` filing, not a payment stop of its own. On-demand's promise not to
preempt is enforced by remedy rather than by a mandate guarantee of physical
service: the buyer may enforce the premature-stop penalty through a case over held
money, and the seller's own exit is the mechanically ruled self-penalty.

Per-part snapshots expose `started`, `stop`, `pendingStop`, `extensions` and
`releaseAt`, beside rate progress and the causal sequence. Approval reserves the
first batch, `once` parts included; no rate accrues before the payee's `start`.
Periods begin at `start` but stay reserved, not earned, until the period ends or
the part stops, and a stop applies its entry's `partialPeriod`; no started-period
clawback is needed. With `{afterStop}` holds this earning rule does not change
payout; with `{for}` holds it moves period payout one period later than earning at
period start would. Exhaustion stops every co-funded part at `fundedThrough` with
cause `terms`, and a top-up before then may rescue them. A part's `end` stops it
with cause `terms` even if no party acts. Parts useful on their own belong in
separate transactions.

Each earned amount stays held until its part's stop plus the dispute window. An
accepted case extension covers current and later earnings, capped from each
amount's normal release by `maxHoldExtension`. A stop does not release money under
an open extension. Partial reverse works before and after a stop while money
remains held. Only the dispute authority opens case extensions and applies ruling
effects, then lifts that case's refs.

These are external dependencies, not behaviour SCM can implement by asserting it in
a normative spec. The foundation vendored the schema and vectors and implements
snapshot-proof verification; this change reads no snapshot field before that
verification and supplies no second proof verifier.

**Vectors, as vendored.** The published vectors cover snapshots before and after
`start`, term ends, a clamped setup-and-rate mandate, partial reversals while
running and after a stop, and same-key stop replay. Two hosted test-mode facts are
recorded from the service: a stop's `settled` figures are not restated after a later
reversal, so reconciliation reads the recorded reversals rather than the stop's
figures; and approval answers `409 insufficient_funds` when the payer's balance
cannot cover the first reservation.

**Qualification limits.** These remain the producer's to close and are qualified at
switch-on (`activate-per-period-compute-servicing`), never by a double:

- the producer's independent HTTP run covered fixed payer and payee treatment only,
  not `chosen`, term ends or reverse;
- the stop-retry vectors are fixed-clock fixtures;
- declaring any rate treatment presupposes the payment authority executes the
  dispute entry's `chosen` stop, which hosted execution has not yet shown (D7).

A missing vector blocks the corresponding conformance claim; double-generated traces
are not published authority evidence.

### D4. Adapter commands and immutable operation descriptors

The hosted payment adapter is extended, not the conditional-escrow port. A
lifecycle `submit {negotiation_id, kind, operation_key, at, payload}` translates
into explicit per-part events with stable derived keys that include the operation
and the part. Outcomes are `accepted`, `rejected`, `pending` or `unknown`; `read`
resolves `unknown` before another monetary delta. Every monetary rate call — start,
`start_billing`, stop, notice and reverse — requires the caller's `OperationStore`
through `OperationKeys.store` and records each descriptor's digest through it with
`check_and_record`, under a part-derived key, before any I/O: a changed retry is
refused before any authority call, and an identical retry reuses its request
identity. The authority's `request_id_reused` is the backstop. There is no
`journaled_digest` parameter. Actor credentials authorize a command; possession of a
handle does not.

The adapter provides rate `start` with activated-delivery evidence, the entitled
stop (a seller notice translates to a stop), voluntary partial reverse, and
verified state and event reads. Delivery authorization is pure and performs no
payment mutation. After activation, the separate `start_billing` effect uses end
service's immutable billing-start identity: end service alone journals that key and
the activated evidence before I/O, delivery retains a reference rather than a second
start intent, and the adapter derives per-part request identities from that key and
replays it without allocating another independently keyed start. The adapter
consumes the versioned, secret-free activated-delivery envelope `kit/deal-lifecycle`
owns rather than defining its own: the envelope carries the verified site
activation record reference and instant, the negotiation, commitment, reservation
and fulfillment identities, and the validated ready-evidence digest. Shared
delivery produces it; convergence passes it through under the end-service effect
key; the hosted adapter checks its version, bindings and activation evidence
against the accepted mandate, and missing, malformed or mismatched evidence refuses
`start` before any authority call. End service's start journal replays its sole
durable intent and key, adopts an unknown `start` from authority records on
recovery, and ends the resource if `start` fails. A verified buyer end, payer stop
or ruling before disclosure follows the foundation's cause classification; only
classified seller non-delivery takes the `delivery_end` handoff. Admission and
disclosure races and the durable journals belong to convergence, not the adapter.

The adapter exports immutable operation descriptors — part, event kind, amount or
`at`, payload or evidence reference, request identity. `PaymentOperation` stores the
canonical event JSON and exposes its digest, never mutable event state, and stays
exported with `describe()` for audit. It exports no end-pricing target or delta API
and no started-period correction journal. The adapter has no database and no daemon
and imports neither `kit/deal-servicing` nor either domain. `start_billing` checks
the activation envelope's version, bindings and activation instant before any call.

A `transaction_stopped` refusal of `start` signals a delivery end, not success. A
repeated stop is already satisfied only when the verified record shows the same or
an earlier effective stop. Transport and server errors stay `unknown` and
retryable. `request_id_reused` with different bytes and `hold_not_reversible`
require repair. `insufficient_held_funds` requires a read of what actually
reversed, not an inference of partial success from the code. `hold_matured` means
the target is no longer locally achievable: the adapter surfaces the shortfall and
the case path, not an endlessly retried refund. No post-release refund command or
journal kind exists.

Conflict classification uses the structured API code at the command boundary:
HTTP 409 `request_id_reused` and `hold_not_reversible` require repair. HTTP 409
`insufficient_funds` during buyer approval becomes `PaymentApprovalInsufficientFunds`,
with an instruction to fund the payer account before retrying. All these codes,
plus `insufficient_held_funds`, `hold_matured` and `transaction_stopped`, occur in
the vendored `ApiErrorCode` enum. Server errors retain their unknown classification.

#### Pure rate authorization

Spot implements `authorize(phase, evidence)`; convergence composes it with physical
admission and journals the effects. A result carries allow, refuse or pending, a
reason, the operation identity, and verified evidence and authority-sequence
references. No phase starts billing. An unknown phase or malformed or cross-deal
evidence refuses. Missing, unreachable, unverifiable or regressing authority state
is pending, never allow.

| Phase | Rate decision over verified, deal-bound evidence |
|---|---|
| commit | Allow an exact, verified approved mandate whose approval was timely; refuse an incompatible or terminal commitment. An expired unapproved mandate cannot become a commitment; approval expiry never invalidates an already approved deal. |
| dispatch / start (physical activation) | Allow a valid commitment, reserved initial funding and no effective stop or absolute end at or before now. A future pending stop allows only until its effective time. Refuse a verified effective stop, end or exhaustion. Missing pre-start `fundedThrough` alone is not exhaustion: use the verified initial reservation, and without it answer pending. |
| disclose | Allow only after a verified rate `start` bound to the journaled billing-start intent and still-valid funding, with no effective stop or end. An unstarted or unresolved start is pending; a definitive start refusal or an effective end refuses. |

A phase invoked at a pending stop's effective instant refreshes authority state;
stale evidence never authorizes work past a known bound. A snapshot decides a phase
only when its `observedAt` lags the storefront's clock by no more than a configured
freshness window (`snapshot_freshness_seconds`, 5 seconds by default; a snapshot
observed ahead of the storefront's clock is fresh). The two clocks are independent
claims and nobody orders them: the window is a seller-side liveness allowance for
skew and latency, and every bound — stop, end, funding — is still checked against
the storefront's `now`. A supplied journaled billing-start result, paired with its
operation key, can definitively refuse disclosure; otherwise a missing verified start
is pending. These are payment choices only: availability, deadlines and dispatch or
disclosure races remain with the neutral composition and the domain, which read no
hosted part fields.

### D5. Started-period treatment is enforced by the payment authority

The foundation codec owns the `settles_through` mapping for stop entries and term
ends; the rate adapter consumes it:

| SCM value | Payment `partialPeriod` | In-progress period |
|---|---|---|
| `started_period` | `charged` | charged in full |
| `last_boundary` | `returned` | billing ends at the last boundary |
| `stop` | `prorated` | billed to the effective stop time |

The payments service computes this price; SCM does not. Negotiation decides the
accepted seller-stop and term-end treatment, not presets or mediation policy. Seller
presets offer the payer `started_period` and the payee `last_boundary`, with a
`last_boundary` term end. Ordinary entitled-stop pricing follows those terms. The
seller self-penalty is a separate mediation package whose rate stops are always
`returned`, on-demand included.

The terms change owns the buyer's acceptance policy, which by default refuses a
payee entitlement or term end whose `settles_through` is not `last_boundary`,
naming the offending term; a buyer may explicitly loosen it, one term at a time
through its per-term waivers. The rate adapter consumes that policy and does not own
a second one: both compute buyers pass their run's `BuyerTermsPolicy` to
`PaymentApproval`, which refuses at approval exactly the default refusals the run did
not waive, and with no policy supplied keeps the waiver-free default refusals.
Approval reads the policy's waivers, not its authority ranking: the dispute authority
was ranked against the listing's registry at selection, which approval cannot see,
and the exact mandate check binds it to the accepted option.

Because the contract expresses every treatment, the shipped presets — `returned` on
the payee's stop and at the term end — reach default buyers wherever a composition
declares those treatments. A seller offering `started_period` on the payee's stop or
term end does so under a declaration listing `charged`, and default buyers refuse it
unless the run waives that term; disclosure alone does not override their policy.
No storefront refund restores a missing payment term.

For authority start S and period P, periods are half-open [S + kP, S + (k+1)P). At
E = S nothing is earned. With S = 0, P = 60, A = 100 and E = 60 all three
treatments charge 100; at E = 61, `charged` keeps 200, `returned` keeps 100, and
`prorated` bills to 61 using the published contract's minor-unit rounding, which
is a qualification gate rather than SCM's own rounding. Without `start`, earnings
are zero, and returned reservations are not earned-money reversals. A buyer's
notice runs from the effective stop, not the click.

The verified stop record determines treatment:

| Winning record | Treatment |
|---|---|
| Payer or payee stop | that authority entry's `partialPeriod` |
| Exhaustion (terms) | the `fundedThrough` boundary; no partial period |
| Absolute part end (terms) | the end's own `partialPeriod`; compute preset `returned` |
| Seller `delivery_end` | the seller files through the dispute adapter; mediation's mechanical self-penalty stops rates now with `returned` and reverses unserved earnings and `once` shares; no seller payment calls |
| `end_delivery` receipt | evidence of surrendered service only; the storefront cannot stop the buyer's billing; the buyer half journals and retries its own stop, and billing runs until it lands |
| Dispute-authority stop or effects | a human ruling states its chosen-entry treatment; `delivery_end` realizes the payer's notice and treatment; payee-agreed claims are mechanical under the foundation guards; hosted execution of the `chosen` entry is a qualification limit (D3) |
| Superseded or equal-time competing request | the authority's recorded winning stop and entry, never local arrival order |
| Unknown cause or ambiguous winning entry | surface an unsupported or unknown state; no inferred monetary action |

A maximum end may cut a period after a late activation; its committed end
treatment prices that period without moving or exceeding the accepted capacity
bound. A pending seller stop creates no later refund obligation; if a payer stop
wins, only its committed treatment applies. Independent discounts and ruling
penalties are separate effects: SCM neither absorbs them into end pricing nor
computes a cumulative target, and the absence of such a target also removes the
cross-actor read, compute and reverse race, not only its duplicate-retry symptom.

Seller-caused unentitled ends and earlier physical failures use a journaled
`delivery_end(cause=payee)` through the dispute adapter to the Agreement's dispute
authority. `at` is never future-dated: a pre-start failure journals immediately
and files at the Agreement start. The seller sends no stop or reverse of its own
on this path, so the authority receives the complete self-penalty package without
reconciling partial seller payment effects. End service owns the end and filing
journal, the evidence store retains the cause and the kept evidence, and an
uncertain filing outcome uses the same operation identity and read-and-retry
contract rather than a second correction journal.

Arkhai mediation's mechanical delivery-end rule is payee agreement under the foundation's guards; its cause=payee branch is the standard self-penalty
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`); its amounts and effects belong to mediation's published mapping, not to
this payment adapter, which derives the parts and terms the ruling reads — the rate
part it stops returned, the setup part it returns only for non-delivery, the penalty it
caps. An unsupported hosted bond is a publication refusal. A self-penalty is a
package of stop, refunds and the capped penalty, bond reserved; a partial seller
path would still need a dispute. Arkhai mediation records disputes so it can act
on bad sellers, banning included, and the buyer may still bring its own case.

The adapter consumes the foundation's `delivery_end` dispute intent and
mediation's request vocabulary and published mapping (foundation section 12.3). No
exceptional-end event kind or field enters the payments vocabulary: the authority
applies ordinary stop and reverse ruling effects. Missing `returned` or
chosen-entry producer evidence blocks qualification of the standard package and is
no ground for a seller-side substitute.

### D6. Seller notice is one command at the authority

A seller notice goes through the foundation's seller-authenticated lifecycle
`submit` route, negotiation-keyed and administrator-principal authenticated. Kind
`notice` is admitted only when the accepted option has a payee entitlement and its
adapter supports rate stops, and it reads the Agreement, never today's listing.
Stable command identity and unknown-outcome recovery follow the foundation command
contract. There is no seller-command correction journal: the authority-hosted
pending stop and `partialPeriod` suffice even if the storefront never resumes.

The command submits a stop now with the explicit affected parts and an optional
future `at`; an earlier time cannot shorten the authority's notice. It returns the
accepted pending stop and its time, or pending, unknown or rejected. Local
acceptance is not authoritative scheduling; a lost response is resolved by `read`.
An earlier buyer stop wins at the authority and later repetition cannot postpone
it. End service follows the earliest authoritative end.

The operator verb is `deals preempt <negotiation-id>` in both storefront CLIs,
forwarding to `notice` through the typed lifecycle client, with an optional `--at`
and a stable operation key; its output is the authority's status and time, not an
invented local deadline. No bespoke preemption route exists. Lifecycle `read` and
`list` expose `pendingStop` during the notice. A seller may hint after acting, but
a push notice and a live storefront are not safety dependencies.

An on-demand refusal of `notice` identifies `delivery_end` as the path for actual
seller non-delivery, not a self-interested override or an automatic filing on
refusal; a lawful end before disclosure keeps its cause without a seller-fault
filing. The administrator interrupt route uses `notice` for a lawful entitled stop
and files `delivery_end` through the dispute adapter for a seller-caused emergency
failure, spot hardware failure included. Alkahest splitter execution and its
defects remain outside this work.

The administrator wire selector is `InterruptDealRequest.interruption_kind =
preemption | failure`, separate from the existing free-text `reason`: required for
rate deals, `failure` by default for once-only deals, so the released route's
callers, which omit a kind and describe operator ends of once-only deals, keep
working. The classification from kind to command lives in `kit/deal-servicing`'s
seller half, not in a domain: preemption is `notice`, refused without a payee
entitlement; failure ends delivery and files `delivery_end`; both require the
reason. Both storefronts mount the administrator interrupt route over that kit
classification — VM's existing route calls the kit, and bare metal gains the route
and its typed admin client — since nothing about interruption differs between the
compute domains. The storefront CLIs have no interrupt verb; `deals preempt` already
sends notice explicitly. The typed clients expose the selector and operation key in
both sync and async variants.

### D6a. The rate buyer end preserves the priced notice

This change owns the rate buyer-end flow the foundation defers to it, in the neutral
buyer half and in both domains' canonical end verbs. The canonical verb is `end` in
both domains — `market end` and `bare-metal end`, registered from shared buyer code;
`bare-metal teardown` is a deprecated alias that prints a notice naming `end` for one
release and is then removed, and once-only end behaviour is what `teardown` did in
v0.3.0. A normal buyer end submits the
payer's stop at the payment authority and sends a `hint`; with a nonzero payer
notice it does not send `end_delivery`, and delivery continues until `watch`
observes the effective stop and end service acts. A hint or read failure never
changes the authority's stop outcome. Zero notice may use the same flow. An
explicit end-now-regardless sends `end_delivery` after the stop and discloses that
service is surrendered before the paid notice expires.

If the payment authority cannot be reached, the buyer half durably journals its
stop and retries it under the same operation key; billing runs until the stop
lands. The outage is not a backdated stop, and the storefront has no authority to
stop billing for the buyer. `end_delivery` carries no `at`: the storefront signs
its receipt time as evidence of immediate surrender, not as authority to issue a
cooperative payment stop. The buyer's `delivery_end(cause=payer)` case and its handling are the foundation's
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-buyers-end`); this change supplies the stop-then-hint rate sequence it starts with.
Both-authorities-down recovery keeps the journal and retry path. The terms change owns the display of a normal stop against
an immediate surrender, and of billing that continues while a stop is pending.

**The buyer's watchdog.** The honest-crash exposure — the resource lost while the
seller's storefront is down, the buyer charged until its own stop lands (foundation
D12) — is bounded from the buyer's side by this change's watchdog: a probe loop in
`kit/deal-lifecycle-buyer` that the buyer's own `buy` command runs in the foreground.
There is no buyer daemon: the buyer used to run a persistent service and that design
was retired; what runs the watchdog is the process the buyer already has. With the
opt-in flag, the `buy` command does not return after delivery: once `available`, it
probes the disclosed access on the configured interval and, when the resource fails a
configured number of consecutive probes, sends the buyer's ordinary entitled stop and
`hint` through the flow above, journals the probe evidence it acted on, and exits. It
exits also when the deal ends by any other path, or when the buyer stops it. The
opt-in, interval and threshold are persisted per deal in the buyer's profile, so
`buy --resume` — each domain's resume of a buy run, VM's `market buy --from <run>`,
with one added where a domain's `buy` has none — re-enters the loop after a restart
where the deal is still running. The
deal read shows `monitored`, `stopped` or `unmonitored`, and a deal whose monitor has
not probed within the freshness window below is shown as unmonitored, never as
protected.

The opt-in says only that the buyer asked for a monitor; a crashed or killed `buy`
leaves it unchanged, so the status rests on the probes themselves (design review 18
F1). Every probe, passed or failed, records its instant per deal in the buyer's
profile beside the opt-in. The read shows `monitored` while `now − last probe ≤
interval + probe timeout`, with a small fixed grace; `stopped` once the watchdog has
journaled its stop; and `unmonitored` otherwise, a deal never opted in included. So
`monitored` means what the bound rests on, a probe ran recently, and a hung loop
reads as unmonitored as a dead process does. The status is the buyer's knowledge of
its own process: the buyer half computes it when it composes the buyer's read, and
the buyer CLI displays it; it is not a field of `LifecycleRead` or any lifecycle wire
model, and the storefront neither sees nor reports it, so released clients are
unaffected.

Rejected: a lock the process holds, which the operating system releases on death but
which a hung loop keeps, answering whether the process lives rather than whether it
probes; and a status only the running command prints, which leaves a read from
anywhere else knowing nothing.

The probe is injected per
domain — whether the VM's or bare-metal host's disclosed SSH endpoint accepts a
connection; the probe uses no credential — so the kit learns no credential format;
what "stops answering" means is that endpoint, not the buyer's workload or its
login. An endpoint that accepts connections while refusing the buyer's key passes.

Rejected: a probe of authenticated access, with process liveness established
separately (design review 35 F2). The stop the watchdog sends is irreversible, and an
authenticating probe turns a key the buyer rotated, an exhausted connection limit or a
slow login into that stop, and brings the buyer's credential into a loop whose kit
learns no credential format; process liveness adds nothing the freshness rule does not
already give. Convergence, which first delivers rate deals and runs the watchdog from
`available`, plans a stronger probe if authenticated loss behind a reachable endpoint
proves a common failure of delivered compute.

The deal read that shows the status is each domain's buyer read of a run's deal.
Bare metal has one, `market bare-metal delivery --run-id`; VM has none, so the read
is registered from the buyer half beside `end`, as 4B.2 registered `end` for both
domains, and VM gains `market delivery` with bare metal's verb moving onto the same
registration (sibling parity). The watchdog applies to rate deals, and while end
service refuses every rate deal's commit (D12) none reaches `available` or discloses
access, so this change proves the loop, its stop and its status without a delivered
deal; convergence, which lifts the refusal, runs the watchdog from `available`, the
buyer's stop landing with the storefront absent among its rows 1 and 2 (D8).

The bound is conditional and stated as one, wherever the watchdog is described: it
covers one failure, the disclosed SSH endpoint no longer accepting connections;
detection takes at most `interval × threshold + probe timeout` after that loss, and
only while the monitor runs; the stop's acknowledgement at the authority and any
priced notice come after that, and billing runs until the stop lands. A probe failure
is the buyer's observation (foundation D9), kept with its instants, and the stop it
triggers is reversible by nothing, so the default interval and threshold are
conservative. The bound holds because each probe starts on schedule, one every
interval: a probe and the loop's check that the deal has ended run side by side,
each cut off at the probe timeout, and the probe timeout never exceeds the interval
(the opt-in shortens the default timeout to a shorter interval). The schedule runs on a
monotonic clock, so a step of the wall clock cannot postpone a probe; the instants
kept are wall-clock time (implementation review 44 F2). The read's freshness rule
compares a kept instant with the reader's wall clock, which a backward step makes
look fresher by the step: an accepted limitation, since the reader is another
process. The watchdog sends nothing the buyer could not send by hand and asks
nothing new of the authority.

A stop the authority refuses is final under its operation key, and leaves the deal
billing. The watchdog then exits with a `rejected` outcome, never `stopped`: it says
the deal is not stopped and billing continues, names immediate surrender (`end
--end-now-regardless`) as the buyer's remaining route without taking it, and `buy`
exits nonzero, as `end` does for a stop the authority did not accept (implementation
review 44 F1). The read still shows `stopped`, which says the watchdog journaled its
stop, beside the lifecycle read's payment state.

### D7. Servicing declarations and identity rotation

The terms change owns the neutral servicing declaration and the publication and
acceptance doors. The declaration is per mechanism: the `settles_through` treatments
the composition has qualified against that mechanism's payment authority, named as
the authority names them — `charged`, `returned`, `prorated` — and whether it services
a separate setup charge (`setup`). It is declared only after hosted qualification;
absent or empty means no rate servicing. This change supplies the materialization
door: `PaymentSettlementData.for_agreement` calls `require_option` on the same
declaration for a rate option, so an option whose treatments or setup charge are
undeclared refuses with `RateServicingUnavailable` and its
`settlement_option_withdrawn_refetch` code, as the acceptance door does, even for
work accepted before a withdrawal. The preset helper checks no contract revision:
derivation and publication already check the declaration. Convergence owns rate
startup, recovery and continuation registration; activation owns the production
switch-on after hosted deployment. Disabling new publication never abandons
materialized deals. No continuation or production declaration is installed here, and
a declaration enables rate offers, not their execution: end service refuses to commit
a rate deal while it services no rate deals (D12).

Declaring any rate treatment presupposes that the payment authority executes the
dispute entry's `chosen` stop (D2), which is qualified at switch-on
(`activate-per-period-compute-servicing`). The derivation does not change for it:
every rate part's dispute entry stays `{account, notice: PT0S, partialPeriod:
chosen}`. If the payments team says hosted cannot execute `chosen`, the fallback is
the open question below.

A change of the payments receipt identity is a cutover (D17): open payment deals
approved under the old identity are drained, or refunded, before it leaves
configuration, and nothing re-anchors a running deal to the new key. The shared
snapshot verifier and the foundation's `receipt_identities` are used as they are
(D18, D22).

### D8. Vectors, qualification and consumer scenarios

Evidence carries one of two labels, those of test-compatibility's "The in-lane
payments double mirrors the service and proves its engine's surface": *lane-double
evidence*, from the in-lane payments double running the vendored engine, and *live
evidence*, from deployed authorities only. Pinned-vector conformance is supporting
evidence, not a third label. Results keep the target identity and mode, hashes and
the control trace, as test-compatibility's "External payment qualification names its
target" requires. Only the external service's own suite qualifies its ledger and
payouts. This change's first-use examples, and the qualification evidence they
produce, use `USD/6`, the asset of the published vectors; other tests keep the asset
they were written with, often `USD/2`, since derivation reads the scale from the
asset named; production reads the Agreement's asset (implementation review 69 F1).

| Scenario or prepared entry point | Executor | Evidence boundary |
|---|---|---|
| Derivation, authorize phases, the setup part, exceptional-end filing; adapter and vector targets | this change's focused kit suites | pinned-vector support; published conformance only for published bytes |
| Buyer stop and hint, seller preempt, setup and rate approval fixtures | this change's CLI and application first use | command mechanics, lane-double evidence |
| One recurring purchase per compute lane through approval and commit, refused at commit | this change's E2E scenarios | lane-double evidence |
| Delivered on-demand and spot, due-work barriers, release and access closure; the rate matrix | convergence | lane-double evidence |
| Hosted four-path qualification | activation | live evidence, from deployed authorities only |

**The recurring-purchase E2E.** One scenario per compute lane runs from a lane-only
servicing declaration listing `charged` and `returned` through approval and commit
against the payments double; its shape is D16's. It asserts the published per-period
price, the accepted money the buyer displays (per-period charge, setup, initial
reserve, maximum term; that the display precedes approval is each buyer's own test,
implementation review 44 F3), the approved mandate's single rate part charging one period's price,
and that end service refuses the commit (D12). It is labelled lane-double evidence,
closes the change index's gap row for a recurring purchase, and convergence extends
it through delivery. Validation runs the compose lanes with Docker and the local Helm part as
its end-to-end evidence; a lane unrun at closeout is a blocker, not a pass.

Unit and vector targets prove derivation, `partialPeriod` edges and exact event
bytes. Kit library integration uses the single clock-injected payments authority
engine in `kit/arkhai-payments`' fixtures directly; the HTTP tooling wraps that same
engine with controls and the mediation composition, and the contract vectors
qualify the engine, so retry and unknown-outcome resolution is proved without a kit
dependency on runnable tooling. HTTP doubles serve lane and e2e qualification.
Application integration proves seller authentication, Agreement binding, CLI
delegation and both domains' preset integration. Smoke is readiness and
authentication only. E2e proves cross-service effects, not arithmetic permutations.

Rate-lane time and progress follow convergence's "Scenarios and evidence" and the
lane double's typed control contract; this change produces kit and vector
evidence and defines no parallel lane clock or progress rule.
Convergence alone owns the consolidated rate qualification matrix
([Scenarios and evidence](../converge-ongoing-compute-leases/design.md#scenarios-and-evidence)),
its runnable scenarios and their execution; this change prepares its entry points
— the rate and setup preset and approval fixtures, the typed buyer-end and seller
notice and preempt commands, the adapter `start` and read seams — and runs no lane
qualification of them. Physical completion evidence proves release and access
closure, not `lease_ended` intent alone. The prepared fixtures use the shipped
presets with default buyers under a lane declaration listing `returned`; a charged
variant is a separate observation whose buyer waives the term through its per-term
waiver, never through the all-terms shorthand. Every behaviour lands with permanent
tests at the level `docs/development/TESTING.md` assigns it.

Published vectors qualify derivation and contract use here; lane-double evidence
never proves hosted internals, and hosted prerequisites are reported before a
scenario runs. Activation lists the producer-published signed snapshot, start and reversal
vectors among the blockers to published qualification; double-generated traces
satisfy none of them and enable no published production servicing.

### D9. `approval_window` and `window` are one term, renamed in stages

Approval expiry has one name, `approval_window`. The released `arkhai.payments.v1`
option parameter is `window`, and a contract carrying its own version is never
changed in place (`docs/guidance/engineering/versioning.md`), so the rename runs in stages over
three releases:

1. This change's release: readers of `arkhai.payments.v1` option parameters accept
   `window` and `approval_window` as one term and refuse a document carrying both;
   rate options are written with `approval_window`; once options keep writing
   `window`, so released buyers keep working. The `arkhai_payments.approval_window`
   discovery field replaces the duplicate projection, with `arkhai_payments.window`
   kept for once options until writers switch. The alias in code carries a comment
   stating its invariant.
2. The next release: once-option writers switch to `approval_window`.
3. The release after: the `window` alias is removed.

Steps 2 and 3, with the `bare-metal teardown` alias's removal (D6a), are one unowned
gap row in `openspec/changes/README.md`, each step triggered by its release. A
registry acceptance test proves rate options carrying `approval_window` pass the
registry, which holds mechanism parameters opaquely. The versioning guidance gains the
staged-rename rule as a path for deprecating a field, not a limit on how a contract
may change.

### D10. Stop requests are distinct from final stops, wire-compatible for released readers

A raw `stop_request` event never ends delivery. The lifecycle contracts carry
`PaymentEvent.settles_through`, `PaymentPartObservation` and `AuthorityView.parts`,
which hold each part's verified rate bounds and its pending and final stops. Notice
maturity can reuse the stop request's original sequence, so the watch reads each
part's final stop outside its event cursor and records it once by authority record;
a changed replay is refused. The lifecycle `read` and `list` routes omit empty `parts`
and null `settles_through`, so a once-deal read stays valid for
`kit/deal-lifecycle-contracts` 0.1.0 clients; the contracts take a minor version, and
a test validates a once-deal read against the 0.1.0 model. A `VersionedEnvelope`
covers an incompatible lifecycle-read change if one is ever needed; nothing else is
added for versioning. The omission lives in the contracts' models, which drop those
fields at their defaults whenever they are dumped, so no producer of the wire shape
can forget it.

Which raw stop is a request follows the parts that bound delivery. In a once-only
mandate a part's stop, its terms end included, stays the deal's payment end, as
released. Beside a rate part every raw stop is a request — the setup part's terms
end at the Agreement start among them, which would otherwise read as the deal's end
— and the deal's end is a rate part's final stop.

### D11. One payments transaction adapter, by composition

One payments transaction adapter implements the foundation's `PaymentAdapter`
protocol (`kit/deal-lifecycle/src/market_deal_lifecycle/adapters.py`). It is composed
of shared components — mandate binding, verified snapshot reads, reverse, event
projection, refusal classification and D4's descriptor recording — and per-part-kind
behaviour: `once` parts reverse, extend and observe; `rate` parts start, stop, take
notice, observe and answer the rate `authorize` phases. A once-only mandate's
`start_billing` is a no-op. There is no inheritance between once and rate behaviour:
no private flag switching a once-only guard off, and no class choice in the seller
stage or either buyer. The stop path does not pre-read, since D4's recording refuses
a changed retry. The protocol's `authorize` gains an optional journaled billing-start
argument, and `start_billing` takes `OperationKeys` instead of a bare key, so it can
carry the caller's operation store.

The journaled billing start is end service's record, its operation key and, once
recorded, its result; end service passes it at disclosure alone and builds the
billing keys over its own operation store. With every pre-read gone, D4's repeated
stop is judged after the send: the authority answers a stop of a stopped part with
the winning stop, which satisfies the new one only when it is effective no later. A
once-only reverse records its descriptor when the caller supplies a store; the
seller's refund path holds none, and relies on the authority's `request_id_reused`
refusal of changed bytes. Whole-part reverse amounts are inferred for every once
part, a setup part beside a rate included, since no once part earns again. A refusal
reason begins with the authority's code, which callers classify by.

The adapter's earlier shape, a rate class subclassing the once-only one and
switching its rate guard off, is the inverted hierarchy this replaces: two classes
whose behaviours contradict — one refuses what the other does — implement a shared
interface or derive from a common base holding only what both do.

### D12. End service refuses to commit a rate deal it cannot service

The servicing declaration says which treatments the payment authority executes; it
does not say that the storefront services a rate deal once it is delivered. Before
convergence composes rate servicing nothing does, so a delivered rate deal would run
with billing started and nobody acting on the buyer's stop, on exhaustion or on a
pending seller stop: the authority still honours each, so the buyer's money is safe,
but the seller serves to the Agreement's maximum term and a lane run would read as a
working rate lease. settlement-configuration's "Terms alone MUST NOT enable recurring
execution" is the invariant this would break.

`kit/deal-servicing`'s `EndService.authorize_delivery` therefore refuses the commit
phase of a deal with a rate part, before it asks the payment adapter and before the
compute delivery path places any capacity (the path authorizes commit first). The
refusal is mechanism-neutral, shared by both compute domains, does no I/O, and sits in
end service, where convergence's rate servicing lives. It is the only place the
promise "delivery fails closed before rate servicing" is enforced.

Rejected: a door in the compute delivery path, which would put a rate concept in the
compute specialization apart from the end service convergence extends, and would need
a once-only projection through both domains' ports; a door in each storefront's settle
path, duplicated per domain against sibling parity; a door at the servicing
declaration's publication, acceptance and materialization doors, which fails before
any money moves but leaves no lane able to reach approval before convergence and adds
a second fact gating offers; and correcting the documents alone, or deferring the
scenario to convergence, either of which leaves a declaration enabling execution.

### D13. The refusal is unconditional until convergence composes servicing

End service refuses every rate deal's commit because it services no rate deals; the
requirement states that invariant and names no seam. When convergence composes rate
servicing, its delta modifies the requirement and its code replaces the refusal.

Rejected: an injected servicer that lifts the refusal when present, which would define
part of convergence's registration before convergence designs it and invite a stub
that delivers unserviced rate deals again; a configuration switch, which turns fail
closed into an operator choice; and lifting on the servicing declaration, which is the
behaviour D12 replaces.

### D14. A refused rate deal waits in repair until the delivery deadline rule

A refused rate deal is `repair_required(rate_servicing_unavailable)`, a new value in
the compute delivery path's closed set of repair reasons, with nothing reserved by
delivery: end service refuses before delivery touches capacity, so an acceptance hold
the domain placed at negotiation (VM's, under a positive `hold_ttl_seconds`) is left
unchanged to lapse at its TTL (validation 58 V1 found the lane scenario expecting it
gone; the owner chose to keep the refusal free of site writes and correct the
scenario, rather than release the hold, whose policy is the hold changes'). A
storefront that gains rate servicing before the deal's delivery deadline delivers it
on its next drive. Once the deadline passes with nothing available, end service's
existing admission rule records the `delivery-deadline` end as seller non-delivery and
journals the `delivery_end(cause=payee, delivered=false)` filing, so a priced setup
part returns through mediation's delivered rule and nothing new decides fault. Until
then the buyer may release its reservation with its own stop. Planning confirms that
each domain's worker drives a deferred deal again after the deadline, and adds the
drive where one does not.

**An earlier buyer stop wins over the deadline (design review 18 F2).** A rate buyer
ends at the payment authority; its hint to the storefront is a courtesy, lost while
the storefront is down, so end service learns of the stop only when the payment watch
records the authority's final stop as a selected end. Admission already prefers a
selected end effective by the deadline, but both domains' recovery admits the deadline
before it reads the authority (VM's cycle admits before `seller.watch`, which
dispatches filings before it polls; bare metal's drives delivery before
`seller.read`), and a recorded classification never changes. So for a deal that is
not once-only — `SellerDeal.once_only`, as D15 reads it — admission's missed-deadline
branch acts only on a successful payment observation made at or after the deadline
that shows no lawful end effective at or before it. Both domains' recovery reads the
authority before admitting the deadline. While the authority cannot be read the deal
stays where it is, in repair with no end recorded and nothing filed; a later drive
after a successful read admits it. An authority outage delays the setup return, and
the buyer's money stays held at the authority meanwhile. Once-only deals keep the
released rule, since their buyer ends at the storefront and nothing earlier can be
unobserved. compute-delivery's "An undelivered deal is handed to the end operation"
names the site's refusal, so the commit-authorization refusal that waits in repair is
not read as one that enters `record_end`.

Rejected: recording a provisional deadline observation and holding its filing until
the stop is resolved, which keeps local progress through an outage but adds a
provisional state beside a classification that never changes once recorded.

The plan left two choices to implementation, settled as built. Admission answers a
held deadline with a third status, `awaiting_observation`, at the unchanged
revision; end service keeps an answer that admits nothing (the coded commit refusal
stays its journaled answer) and turns an allow into pending, and the compute
delivery path answers pending. Rejected: `retry`, which callers read as a stale
revision and retry at once, and `ended` with nothing recorded, which would hand an
unended deal to the end operation. The observation instant is a new table,
`servicing_payment_observations`, holding the storefront-clock instant taken before
each successful payment read, written in the transaction that records what the read
showed. It is its own schema set, created by an ordinary migration appended to each
storefront chain, since deployment-state lets only the store-open migration tolerate
objects already present. Rejected: a column on the watch's tables, which hold a
contract model that forbids extra fields, and adding the table to the store-open set.

End service tells the path why it refused through an optional closed `code` on
`DeliveryAuthorization` (`kit/deal-lifecycle`), absent on every other answer:

```python
DeliveryAuthorization(status="refuse", reason="rate servicing is not composed in this storefront",
                      code="rate_servicing_unavailable",
                      operation_id="n-123:commit:4", evidence_refs=["tx-abc"])
```

The path maps that code to the repair reason; every other refusal stays
`no_accepted_deal`. Earlier journaled acknowledgements, which lack the key, still read.

Rejected: an immediate classified hand-off and filing at refusal, which cannot be
undone and charges the seller's premature-stop penalty for a configuration mistake
before the deadline it agreed to; a silent pending, which shows an operator nothing;
matching the free-text reason, which breaks when the wording changes; and reusing
`no_accepted_deal`, which reports a missing settlement that is not missing.

### D15. The door recognises a rate deal by the committed seller projection

The door reads `SellerDeal.once_only`, which every domain registers in the
transaction that registers the deal's delivery record, as the administrator interrupt
classification (D6) does. A registration that never set the flag reads as a rate deal
and is refused; a deal with no seller registration is refused without a code and
reported `no_accepted_deal`.

Rejected: a `once_only` column on the delivery record, which stores the fact twice and
needs a migration; and asking the payment adapter, which makes every adapter answer a
question the neutral projection already answers.

### D16. The recurring-purchase scenario runs through commit and ends by the buyer

`market buy` and `market bare-metal buy` approve and commit in one run, so each lane's
scenario runs through both:

1. The lane declares `charged` and `returned`; the seller publishes a recurring option
   through a pool override or VM's listing creation, with an approval window leaving
   runway (approval window + delivery deadline + one period within
   `max_duration_seconds`).
2. The shipped `buy` runs with a default buyer; the scenario asserts the published
   per-period price, the accepted money the buyer prints on stderr (its order before
   approval is each buyer's own test), and the approved mandate's single rate part
   charging one period's price.
3. After commit it asserts what existing interfaces show: the deal never becomes
   available, the site holds no reservation delivery made for it (only VM's
   acceptance hold, still `reserved`, until its TTL lapses), and the payments double
   records no rate `start`. The repair reason is proven at the lowest level that sees it —
   library integration in `kit/deal-servicing` and `domains/compute/delivery` — and
   asserted by the scenario only where a storefront interface already exposes it.
4. Cleanup is the buyer's own `end`, the payer's stop and hint, since the seller's
   refund refuses a rate deal; with zero payer notice and nothing started, the
   reservation returns, and the scenario asserts the payer's balance restored. It
   leaves no hold, rule or held loop. It does not wait for the delivery deadline:
   the buyer's hint makes the storefront poll the payment authority, and the payment
   watch records the payer's final stop as the deal's selected end, effective before
   the deadline, so admission never takes the deadline branch and no seller
   non-delivery is filed (D14's barrier covers a hint that is lost). The scenario
   asserts that the seller's lifecycle read shows that end and no `delivery_end`
   filing.

Rejected: an approve-only buyer option, buyer surface that exists only for the test;
and driving `PaymentApproval` directly, which skips the shipped display the scenario
asserts.

### D17. A receipt identity change is a cutover

When the payments service changes the key that signs its receipts, every buyer and
storefront moves its configuration to the new identity, and open payment deals
approved under the old one are drained, or refunded, before it leaves configuration.
Nothing re-anchors a running deal to the new key. Once the old identity is no longer
trusted, each deal it approved stops verifying everywhere: snapshot reads, admission,
stored-receipt revalidation and the storefront's refund, which then answers that no
verified payment exists — so refunds come first. The foundation's
`receipt_identities` may list both keys for the moment of the switch, so a fresh
approval does not fail while clocks and configurations differ; it keeps no deal alive
past the date the old entry is removed.

Draining is viable because no deployed deal outlives one. The released marketplace's
payment deals are once-only with a guaranteed end, and no rate deal exists before
convergence composes rate servicing and activation switches it on: end service refuses
to commit one (D12). Migration and backwards compatibility are engineered only for
what has been deployed, so rotation machinery for rate deals that have never run is
not built ahead of them. A drain can still last as long as the dispute window and any
hold extension, unbounded when `case_hold_max_seconds` is omitted; a seller facing a
fixed switch date ends or refunds what remains. The switch needs advance notice of
the rotation from the payments service, which publishes no rotation mechanism today.

The key's retention matters only for what a party must keep verifying. The verifier
accepts an embedded old receipt only while its issuer is configured — through the
receipt's own signature, or as a configured retiring identity's receipt attested by a
current-key snapshot — and every snapshot must be signed by an identity valid at the
snapshot's own claimed `observedAt`. A retired identity left configured with a closed
window therefore still lets a holder of that key, were it compromised, sign a snapshot
backdated into its window; removing the identity at the cutover ends that.

Rejected, until a deployed deal outlives a drain (the unowned gap D24 records):

- **A caller-held anchor in the verifier**: a persisted current-key snapshot standing
  in for the receipt issuer's pin. It adds a trust input that cannot be re-proved once
  the issuer is removed, has to reach every seller verification (adapter, admission,
  stored-receipt revalidation, refund) and both buyers, makes convergence supply it to
  every read, and still drains once-only deals.
- **Current-key attestation with no issuer pin**: a current-key snapshot vouching for
  any embedded receipt bound to the deal. It drops the receipt's own signature from
  every snapshot path, and stored-receipt revalidation still needs the old key.
- **Retired identities that verify receipts only**: a third identity state verifying
  receipts approved in its window and no snapshot. It closes the backdating exposure
  without per-deal work, and is the design to resume from when the gap is picked up.
- **Closed-window identities kept until every dependent deal drains, with no switch
  date**: the backdating exposure lasts as long as the longest case.

### D18. The shared verifier is used unchanged

Settlement-servicing's "Snapshot verification accepts bounded identity history" keeps
its requirement text, and this change modifies no verifier. The foundation is
archived with its snapshot verification complete, so the verifier is permanent code in
`kit/arkhai-payments`, consumed here; no foundation round remains to own a change to
it. Its one scenario, "Rotation re-anchors an old receipt", is reworded to what the
verifier does (design review 35 F1): it returns a verdict and supplies no re-anchoring
evidence, accepting a current-key snapshot that embeds a configured retiring identity's
receipt only while that identity stays configured. Left as it was, it would contradict
D17's requirement that the kit re-anchor no running deal. A MODIFIED delta cannot drop a
scenario the permanent requirement has, so the delta removes the requirement and adds
it back, its text unchanged, as "Snapshot verification accepts configured identity
history" with the reworded scenario. Rejected: keeping the old scenario title over a
reworded body, which leaves the re-anchoring claim in the title; and a MODIFIED delta
extending the verifier, which D17 leaves without a purpose.

### D19. Buyers follow the same cutover

Both compute buyers move `service_identity` to the new key at the switch, as the
storefront does, and need no code: their lifecycle reads verify under their own
configuration, and a buyer's open deals drain with the seller's. Rejected: buyers
holding an anchor of their own, which only D17's rejected anchor would need.

### D20. Draining is the operator's procedure

The payments kit carries no retirement inventory. The operator finds a seller's open
payment deals through the seller read and list that already exist, and follows the
cutover rule in `openspec/specs/settlement-configuration/configuration.md`: drain or refund before the
change. A `livemode` change is the same cutover, as that rule already states. Rejected:
a kit inventory of the deals resting on a retiring key, which served only re-anchoring.

### D21. Convergence takes on no rotation work

`converge-ongoing-compute-leases` consumes no re-anchoring evidence and reports no
retiring-key dependency. Withdrawn from it: the overlap paragraph of its D7, task 3.5's
re-anchoring, its deal-lifecycle requirement that servicing request and persist
re-anchoring evidence during an overlap, and row 11 of its qualification matrix.
Convergence is in design and owes a reverification of its design against the code; its
own design amends its documents, and this change names the withdrawal in "Dependencies
and ownership" and in convergence's index notes rather than editing its directory.

### D22. Configuration stays as the foundation built it, less one defect

`receipt_identities` keeps the foundation's validation: the current `service_identity`
listed, and retiring entries dated. The validation section 5's work in progress added
— one non-retiring identity, none listed twice — is withdrawn: it made "current"
unambiguous for re-anchoring alone. Kept: `pinned_snapshot_verifier`, which the kit's
examples and several kit and domain tests compose, binds `config.receipt_trust` rather
than `service_identity` alone, so it honours the configuration the seller stage's own
verifier already honoured, and the stage delegates to it rather than bind its own
copy. That is a small, understood defect against "Snapshot verification accepts
bounded identity history", fixed here
(`docs/guidance/workflow/changes.md#defects-found-during-a-change`).

### D23. No anchor reaches the seller's refund

With no anchor (D17), nothing needs to reach `reverse_now`, the storefronts'
stored-receipt revalidation sites or a `ReanchoringEvidence` constructor. The refund's
`NotPaid` answer for a deal whose identity was removed is why D17 refunds before the
switch.

### D24. Documents that follow the cutover

The proposal's overlap-and-re-anchoring bullet, its once-only re-anchoring non-goal and
settlement-servicing's "rate-deal identity re-anchoring" capability line give way to the
cutover. D3's qualification limits drop rotation: there is no cross-key vector to want
and no live rotation to qualify at switch-on. The roadmap drops "a rotation re-anchored"
from this change's row and "identity-rotation overlap" from convergence's, and
`openspec/changes/README.md` records one unowned gap in place of section 5's buyer row:
a receipt key change drains every open payment deal, and re-anchoring running deals
across it is not designed, to be revisited when rate deals whose maximum term makes
draining impractical reach production or when the payments service publishes a
rotation mechanism. Section 6's qualification task drops rotation-overlap preparation
and adapter re-anchoring evidence, and the test-compatibility delta requires no
re-anchoring evidence. Closeout's promotion drops rate-only rotation from
settlement-servicing's architecture and identity overlap from the deployment guide,
which gains the cutover rule instead (design review 35 F1).

### D25. Implementation cadence

Recorded under "Implementation cadence" below.

### D26. A buyer updates its receipt identity before approving

The buyer checks the payments receipt only after `approve` has moved funds, so a buyer
whose configuration still names the old identity after a switch has its funds approved
and held while its `buy` fails, and never posts settlement. The cutover rule in
`openspec/specs/settlement-configuration/configuration.md` states it: buyers update their receipt
identity before approving after the change. Rejected: checking the service's current
key before approval, which needs the service to publish its key and is migration
engineering for a rotation never deployed.

## Implementation cadence

Round 2 continues with one session per slice, each committed on its own: the
end-service door with its refusal code, repair reason, tests and the corrected
`approve_rate` comment in VM's `test_lifecycle_admin.py` (D12–D15); the
recurring-purchase scenario in both lanes (D16, task 4B.5); the buyer's watchdog
(4B.6); section 5, now one short session that withdraws section 5's work in progress
— its anchor, re-anchoring module, inventory, configuration validation, README section,
deployment-guide edit and their tests — keeping the `pinned_snapshot_verifier` binding
and its test (D17–D22), together with the wording correction design review 35's
triage made to the watchdog's stated bound (D6a, task 4F.7), the other small
correction left from a design review; and qualification evidence (section 6). Round 2's review and
validation cover them together, with 4A and 4B.1–4B.4, before pre-closeout.

## Rejected alternatives

- A payee-advanced horizon or vouch: a dishonest seller can advance it; the buyer's own stop and a case over held money are the guarantee.
- A background buyer service to run the watchdog: the buyer's persistent service and agent were retired as a design direction; the `buy` command stays in the foreground instead, and the bound is stated as conditional on its running.
- Renewable site deadlines as buyer payment protection: the site and the storefront are both the seller; activation and renewal policy is a seller-value decision elsewhere.
- A required minimum spend, or a service request for one: churn is priced by setup or refused through seller policy.
- An extra `once` fee labelled a minimum: setup is additive, not usage drawdown.
- A backdated or effective-time payee stop: a past exceptional end is filed through the dispute adapter and mediation applies the standard self-penalty package.
- Local notice-stop scheduling: it dies with the storefront; pending stops belong at the authority.
- Claiming the on-demand mandate prevents physical seller preemption: the premature-stop penalty and the buyer's case over held money are the remedy, and the seller's own exit is the mechanically ruled self-penalty.
- A seller-side exceptional-end stop or reverse, explicit restitution entries, implicit favourable-payee stop privileges, a payee notice waiver, or a payer early release: `delivery_end` is a dispute filing, not a partial payment path.
- A compound termination authority at payments — a transaction-level event ending billing at an authorized past time, settling rates `returned`, refunding `once` parts by unserved share and forfeiting a bond: deferred until hosted bonds are designed, and it would also need dispute-authority recording so terminations inform action against bad sellers. The foundation owns this record.
- A payer `start`, or a start at approval: `start` is the payee's responsibility after provisioning, and an early start is disputable.
- Reverse-before-stop as a safety rule: `afterStop` holds preserve reversal after a stop.
- An unsupported post-stop refund journal: reverse already works after a stop while money is held, and paid-out money is outside that primitive.
- Storefront cumulative-target end refunds: they bind only a cooperative seller, race independent authority rulings, and absorb unrelated discounts.
- Boundary-aligned seller notices as a substitute for `partialPeriod`: they change the offered notice and cannot encode an arbitrary committed treatment.
- Local final-period pricing: the payment term and the authority decide it.
- A separate per-period mechanism or domain adapter: generic parts and authorities serve both domains.
- A new preemption route or an escrow-keyed admin verb: lifecycle `submit` is already the authenticated command boundary.
- Re-anchoring running deals across a receipt key change, by an anchor, by current-key attestation or by receipt-only retired identities: no deployed deal outlives a drain, so a key change is a cutover (D17).
- Proposed qualification as live proof: a double cannot establish deployed authority behaviour.
- An interim contract revision with only fixed charged semantics, and offers fixed to `started_period` until `returned` became expressible: the published contract already expresses every treatment, so the limit is hosted execution, which the servicing declaration expresses (D7).
- A lane-only `proposed` declaration binding a fixture payments identity and mode at materialization: the servicing declaration is treatments and a setup flag, declared after qualification, and identity is the receipt verifier's (D7).
- A bare-metal preset with no setup default and a VM preset defaulting to zero: setup is the seller's choice in both domains, and the domains differ only where an explicit need is identified (D1).
- Keeping the released `window` as the only name: one name keeps the client and model clean, and the staged rename keeps released buyers working (D9).
- Keeping the rate adapter as a subclass of the once-only adapter, with its guard switched off by a private flag or a class-level declaration: contradictory behaviours do not subclass one another (D11).
- Refusing any snapshot observed before the storefront's `now`: two observers' clocks cannot be ordered across a network boundary, so a strict comparison only turns skew into pending answers; a bounded freshness window with bounds checked at the storefront's clock is the liveness rule (D4).
- Moving sections 4–6 out of this change to the Goal 8 MVP replan: each change is mergeable to `dev` on its own merits, and splitting a change under development would undercut the premises of code already built.

## Open questions

- **A bound fallback for the dispute entry.** If the payments team says hosted cannot
  execute the dispute entry's `chosen` stop, a rate option would bind a fixed
  `charged` dispute entry into its settlement parameters instead. Until then the
  derivation keeps `chosen` (D7), and nothing here builds the fallback.

## Dependencies and ownership

- `agreed-evidence-and-early-termination` (whole change): the codec and authority
  derivation, the vendored contract and the shared snapshot verifier, used unchanged
  (D18), the dispute intents and mediation's published self-penalty mapping, and the
  activated-delivery envelope. The seller never substitutes direct payment calls
  for the filing path; a spot emergency exit uses it rather than an extra stop
  entry.
- `negotiate-open-ended-compute-terms` (whole change, archived): the agreed-price
  accessor and period unit, the listing bounds, the option shape and start-identity
  rule, the servicing declaration, the whole-second start resolution before
  signature, the per-term buyer waivers, and the publication and acceptance doors.
  The terms change owns generic publication emission through an injected
  preset-helper interface; this change supplies the hosted helper and the
  materialization door. Convergence alone owns startup.
- The foundation's in-process contract fakes gate kit library integration; the
  runnable lane doubles gate lane evidence only, and no kit imports the double
  tooling.
- `converge-ongoing-compute-leases` depends on this change and on
  `unify-compute-delivery-path` as whole changes; it owns funding timers and the
  complete rate qualification matrix, and takes on no rotation work (D21).
  `activate-per-period-compute-servicing` owns the hosted four-path execution.

The shared requirement "The payments mandate is derived exactly from the
Agreement" archives in the order foundation, then this change: this change's
MODIFIED text is a superset of the foundation's `once` clauses plus its rate and
setup branch, and a once-only option without early-termination entitlements
authorizes no `start` or `stop`. A later codec change is carried into both before
archive. The foundation's buyer-orchestration requirement owns the buyer end and
outage behaviour; this change adds only the rate stop-then-hint sequence with
service through the priced notice. The foundation owns the codec mapping and the
neutral activated-evidence envelope; this change owns hosted rate `authorize` and
the consumption of the journaled exceptional-end filing path; mediation alone owns
its ruling computation.

Before convergence lands, first use runs on lane-only approval and command
fixtures, and end service refuses to commit a rate deal (D12): that proves a pending
authority stop, not a working delivered spot lease. Convergence modifies that
requirement when it composes rate servicing (D13). Production rate publication
stays dark until its servicing doors are composed, and that fixture is not
production enablement.

## Design promotion record

Destinations are planned, not claims of implemented behaviour.

| Accepted decision | Permanent location |
|---|---|
| D1–D2 rate derivation, the setup part, presets and the exact check | `openspec/specs/settlement-servicing/spec.md`; `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| D3 external contract context | `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" |
| D4–D5 pure rate authorization, envelope consumption, operation identity, authority-priced `partialPeriod` and the journaled exceptional-end filing | `openspec/specs/settlement-servicing/spec.md` and `architecture.md` |
| D6–D6a seller notice, the rate buyer end and the CLI | `deal-lifecycle` `spec.md` (foundation-created; [delta](specs/deal-lifecycle/spec.md)) and `architecture.md`; `docs/development/ARCHITECTURE.md`, "Release" |
| D4's freshness window | `openspec/specs/settlement-servicing/spec.md`; `openspec/specs/settlement-configuration/configuration.md`, "Settlement consumer configuration and cutover", for `snapshot_freshness_seconds` |
| D5's approval policy | `openspec/specs/buyer-orchestration/spec.md` |
| D6's administrator interrupt classification and routes | `deal-lifecycle` `spec.md` and `architecture.md` for the kit classification; `openspec/specs/compute-delivery/spec.md` for both compute storefronts' route, since no bare-metal storefront specification exists and compute-delivery is the capability whose requirements bind both ([delta](specs/compute-delivery/spec.md)) |
| D6a's end verb | `deal-lifecycle` `spec.md`; `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/test-compatibility/spec.md` for the bare-metal purchase's `end`; `deal-lifecycle` and `buyer-orchestration` `architecture.md`, which still name `market bare-metal teardown` |
| D7 declarations, the materialization door and the `chosen` presupposition | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/settlement-servicing/spec.md`; `openspec/specs/deal-lifecycle/architecture.md`, "External authorities"; `openspec/specs/settlement-configuration/configuration.md` |
| D17 a receipt identity change is a drained cutover, and why draining suffices | `openspec/specs/settlement-configuration/spec.md` ([delta](specs/settlement-configuration/spec.md)); `openspec/specs/settlement-servicing/architecture.md`, "Charge-first payment settlement", beside its current/retiring pins, for why a key change drains rather than re-anchors; `openspec/specs/settlement-configuration/configuration.md`, its cutover paragraph |
| D18 the verifier unchanged, its scenario reworded to what it does | `openspec/specs/settlement-servicing/spec.md` ([delta](specs/settlement-servicing/spec.md)), "Snapshot verification accepts configured identity history", replacing "Snapshot verification accepts bounded identity history" |
| D19–D20, D23 buyers alike, draining by procedure, no anchor | No permanent destination beyond D17's: each states what the system does not add |
| D21 convergence's withdrawn rotation work | `openspec/changes/README.md`, convergence's notes (its own design amends its documents) |
| D22 `pinned_snapshot_verifier` honours `receipt_identities` | No new destination: the settlement-servicing requirement "Snapshot verification accepts configured identity history" (D18's rename of "… bounded identity history", text unchanged) already requires it |
| D24 the re-anchoring gap and roadmap criteria | `openspec/changes/README.md`, unowned gaps; `docs/development/ROADMAP.md` |
| D26 buyers update their receipt identity before approving after a switch | `openspec/specs/settlement-configuration/configuration.md`, its cutover paragraph |
| Migration and backwards compatibility are engineered only for what has been deployed | `docs/guidance/repository/package-versions.md`, "Compatibility is owed to what a release has shipped", with a pointer from `docs/development/ARCHITECTURE.md` |
| D8 vectors, evidence labels and the recurring-purchase E2E | `openspec/specs/test-compatibility/spec.md` and `architecture.md`; `kit/arkhai-payments/README.md` |
| D9 the staged `approval_window` rename | `openspec/specs/settlement-configuration/spec.md` (wire field and alias); `docs/guidance/engineering/versioning.md`, "A field may be renamed or retired in stages" |
| D10 stop requests and final stops | `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/settlement-servicing/spec.md` |
| D11 the composed transaction adapter | `openspec/specs/settlement-servicing/spec.md` and `architecture.md`; `openspec/specs/deal-lifecycle/spec.md` for the protocol |
| D12–D15 end service's refusal of a rate deal it cannot service, its refusal code and the projection it reads | `openspec/specs/deal-lifecycle/spec.md` and `architecture.md`, "One end instant, transactional admission" (where fails closed is enforced); `openspec/specs/compute-delivery/architecture.md`, "Commit and hold adoption" |
| D14's repair reason and the site-refusal wording of the undelivered hand-off | `openspec/specs/compute-delivery/spec.md` |
| D14's deadline barrier for a deal that is not once-only, its `awaiting_observation` admission answer and the payment observation instant | `openspec/specs/deal-lifecycle/spec.md` (with "Admission shares the end-service transaction and revision") and `architecture.md`; the observation table's migration in `docs/development/DEPLOYMENT_AND_CONFIG.md` and `kit/deal-servicing/README.md`, "Schema" (both updated with the code) |
| D6a's watchdog status: the last-probe freshness rule, buyer-local and off the wire; the probe schedule on a monotonic clock and the probe timeout no longer than the interval, which its bound rests on; the `rejected` outcome of a refused stop and `buy`'s nonzero exit on it | `openspec/specs/deal-lifecycle/spec.md` (with 4B.6's watchdog requirement); `openspec/specs/buyer-orchestration/architecture.md` |
| D16 the recurring-purchase scenario's shape | `openspec/specs/test-compatibility/spec.md` |
| Each change is mergeable to `dev` on its own merits | the change workflow's guidance under `docs/guidance/workflow/`, where closeout's guidance placement puts it |
| Sibling-domain parity is checked before adding behaviour to one domain | the guidance under `docs/guidance/`, where closeout's guidance placement puts it |
| A versioned contract's field is renamed or retired in stages | `docs/guidance/engineering/versioning.md`, "A field may be renamed or retired in stages" |
| Contradictory classes do not subclass one another | `docs/development/ARCHITECTURE.md` |
| A timestamp is its source's claim, never an ordering | `docs/development/ARCHITECTURE.md`, authority boundaries |
| The adapter and continuation boundary | `docs/development/ARCHITECTURE.md`, "Kit areas" and "Settlement servicing" |
| Campaign and Goal 8 currency | `openspec/changes/README.md` and `docs/development/ROADMAP.md`, at design merge and again at closeout |
