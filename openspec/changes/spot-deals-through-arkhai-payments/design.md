# Design

## Context

The lifecycle foundation, [`agreed-evidence-and-early-termination`](../agreed-evidence-and-early-termination/),
is the frame: the protocol ends at commitment, and everything after it is
authority records and the signed bytes each party keeps. The terms a deal
carries — `early_termination {version, entitlements, settles_through,
premature_stop_penalty?}` and `adjudication` — live under the
selected option's `lifecycle`, beside its `price` and `settlement` (foundation D5,
"The option's shape"; terms D4). Payment derivation consumes that shared codec; it
keeps no mechanism-specific copy of the terms.

`kit/arkhai-payments` derives a single `once` part today. Its vendored schema is an
earlier publication that predates per-part authorities (the revised contract has no
mandate-level authorities), `maxHoldExtension` and `pendingStop`. The revised contract
this design builds on is an implementation gate, not a description of the current
generated models; the foundation vendors it once for both changes.

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
listing or a registry cache. The accepted-rate carrier or digest that
`negotiation-driven-capacity-resize` task 2.1a chooses is an input gate: without
resolvable bound pricing, materialization is refused.

**Setup.** An optional `setup_amount`, a positive integer minor-unit string in the
option's asset, adds a `once` part beside the rate; omission means no setup part.
It is an additional charge, not `max(setup, usage)`, visible before approval and
bound into the option ID. A preset populates it from an explicitly configured setup
price and refuses an incomplete configuration rather than inventing an amount. The
bare-metal composition's preset ships no default: a bare-metal seller states its
setup price or publishes no recurring option, since provisioning a host is the
cost churn imposes. VM's preset may default it to zero. Churn beyond the setup
charge is the seller's to price differently or to refuse through its negotiation
policy; neither domain has a required minimum spend.

The setup charge is owed by the buyer from approval: it prices the provisioning
the buyer's commitment triggers, so a buyer who stops — before or after activation,
seconds after approval or days later — leaves it with the seller, and a lawful
preemption after delivery leaves it earned. It returns to the buyer on one ground
only, the seller's own non-delivery: the seller files `exceptional_end` through the
dispute adapter and the mediation self-penalty package returns all of setup for an
undelivered deal and none for a delivered one; a term end that arrives before
activation is non-delivery. A controlling lawful end before disclosure keeps its
own attribution and is not seller fault, and keeps the setup charge.

The part is an ordinary `once` part with a fixed end, the later of the Agreement's
`start_utc` and the approval instant, held through the dispute window after it;
the window, days, covers provisioning, minutes to hours, so the self-penalty's
reversal reaches it. It needs nothing the published contract lacks: no link to the
rate part's `start`, no activation-anchored end, no fallback. A `once` end has no
rate `partialPeriod`. The buyer is told before approval that the setup charge is
kept if they stop and returned only if the seller never delivers.

| Preset | Parts | Entitlements |
|---|---|---|
| On-demand | setup `once` by default + time rate | payer `{notice_seconds: 0, settles_through: started_period}`; no seller stop entry |
| Spot | setup `once` by default + time rate | payer `{notice_seconds: 0, settles_through: started_period}`; payee with its priced notice |
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
notice files `exceptional_end` and pays the capped penalty after the refunds. Buyer
acceptance and display of the penalty are the terms change's.

No class flag is persisted or used for dispatch. One pool may publish on-demand and
spot at different rates.

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
The intended preset is `last_boundary`. Until `returned` is expressible, every
interim rate offer, on-demand included, explicitly commits `started_period` at the
term end and discloses the final partial-period charge; publication and acceptance
refuse unexpressible terms, and SCM implements no compensating refund.

The foundation owns per-part authority derivation from the common codec. This
change adds the rate-specific `start` permission, period, reservation and end
fields. `start` is payee-only. Seller stop entries exist only for accepted
entitlements: on-demand has none, spot has its priced notice entry. Stop entries
carry the entitled party's `notice_seconds` and the `partialPeriod` mapped from its
`settles_through` (D5). An exceptional end grants no seller stop entry or implicit
payment privilege: the seller files a dispute and mediation acts under its own
entry; there is no additional seller restitution entry and no multiple-entry
dependency. On the returned-capable revision every rate stop entry and rate end
carries an explicit `partialPeriod`, `once` ends carry none, and the dispute
authority's rate stop entry is `{account, notice: PT0S, partialPeriod: chosen}`,
under which a stop carries its own charged, returned or prorated treatment. On the
interim revision these fields are absent and the vector-qualified fixed charged
semantics apply, dispute stops included; chosen-entry treatment is unavailable.
Only the dispute authority extends and lifts holds. Reverse permissions remain the
payee's and the dispute authority's. Setup uses the foundation's `once` permissions
and its own end, the later of the Agreement start and approval, without rate start
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

The revised contract has per-part authorities `{stop: [{account, notice,
partialPeriod}], reverse, extend, start}`, with `start` on rate parts. Until
`partialPeriod` is vendored only its expressible charged semantics may be offered;
D5 defines that fail-closed interim. The contract also carries `maxHoldExtension`,
an optional per-part `end` (with `partialPeriod` required for rate ends on the
returned-capable revision), `{afterStop: d}` holds, `start` and `stop` with an
optional part, `stop` with an optional `at`, and `extend`/`lift`. An entitled stop
takes effect at `max(at ?? now, now + senderNotice)` at authority receipt and is
never backdated. There is no implicit role-based or buyer-favourable stop
privilege, no payee waiver of payer notice, and no payer early-release waiver: each
stop is authorized by an explicit mandate entry, and reverse uses the existing
reverse authority. The earliest pending stop wins and cannot be withdrawn. The
adapter sends explicit part IDs even where a whole-transaction shorthand exists.

The seller's emergency exit, a spot hardware failure included, is the journaled
`exceptional_end` filing, not a payment stop of its own. On-demand's promise not to
preempt is enforced by remedy rather than by a mandate guarantee of physical
service: the buyer may enforce the premature-stop penalty through a case over held
money, and the seller's own exit is the mechanically ruled self-penalty. Interim
charged-only fixtures prove only their named mechanics and cannot qualify the
standard returned self-penalty.

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
a normative spec. The foundation vendors the schema and vectors and implements
snapshot-proof verification in its round 2; this change gates on that verified
interface before reading any snapshot field and supplies no second proof verifier.

Outstanding qualification requests to the service: signed snapshot vectors, paired
snapshots before and after `start`, a mixed `once`/`rate` mandate vector, partial
rate-reversal integration traces before and after a stop, and the reservation and
charge behaviour where a late rate start approaches the absolute term bound. A
missing vector blocks the corresponding conformance claim; double-generated vectors
are not published authority evidence.

### D4. Adapter commands and immutable operation descriptors

The hosted payment adapter is extended, not the conditional-escrow port. A
lifecycle `submit {negotiation_id, kind, operation_key, at, payload}` translates
into explicit per-part events with stable derived keys that include the operation
and the part. Outcomes are `accepted`, `rejected`, `pending` or `unknown`; `read`
resolves `unknown` before another monetary delta. The caller's durable journal
rejects same-key reuse with changed content before any I/O; the stateless adapter
compares the supplied journaled descriptor or digest with its new descriptor, with
the authority's `request_id_reused` as the backstop. Actor credentials authorize a
command; possession of a handle does not.

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
classified seller non-delivery takes the `exceptional_end` handoff. Admission and
disclosure races and the durable journals belong to convergence, not the adapter.

The adapter exports immutable operation descriptors — part, event kind, amount or
`at`, payload or evidence reference, request identity. It exports no end-pricing
target or delta API and no started-period correction journal. The caller writes
each descriptor durably before calling. The adapter has no database and no daemon
and imports neither `kit/deal-servicing` nor either domain.

A `transaction_stopped` refusal of `start` signals a delivery end, not success. A
repeated stop is already satisfied only when the verified record shows the same or
an earlier effective stop. Transport and server errors stay `unknown` and
retryable. `request_id_reused` with different bytes and `hold_not_reversible`
require repair. `insufficient_held_funds` requires a read of what actually
reversed, not an inference of partial success from the code. `hold_matured` means
the target is no longer locally achievable: the adapter surfaces the shortfall and
the case path, not an endlessly retried refund. No post-release refund command or
journal kind exists.

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
stale evidence never authorizes work past a known bound. These are payment choices
only: availability, deadlines and dispatch or disclosure races remain with the
neutral composition and the domain, which read no hosted part fields.

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
naming the offending term; a buyer may explicitly loosen it. The rate adapter
consumes that policy and does not own a second one.

Until the returned-capable contract revision is vendored, publication and
acceptance refuse every unexpressible value. The interim rate offer, spot or
on-demand, explicitly commits `started_period` on each present entitlement and,
when only a charged end is expressible, on the term end too. Default buyers refuse
it: disclosure alone does not override their acceptance policy, and an interim
scenario configures its buyer to accept `started_period` for every affected term,
a charged term end included. Rate offers reach default buyers only once the
vendored revision expresses `returned` on seller stops and term ends. No storefront
refund restores a missing payment term.

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
| Absolute part end (terms) | the end's own `partialPeriod`; compute preset `returned`, interim `charged` |
| Seller `exceptional_end` | the seller files through the dispute adapter; mediation's mechanical self-penalty stops rates now with `returned` and reverses unserved earnings and `once` shares; no seller payment calls |
| `end_delivery` receipt | evidence of surrendered service only; the storefront cannot stop the buyer's billing; the buyer half journals and retries its own stop, and billing runs until it lands |
| Dispute-authority stop or effects | a human ruling states its chosen-entry treatment; `buyer_end` realizes the payer's notice and treatment; only the seller self-penalty is mechanical; the interim fixed charged semantics remain a qualification gate |
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
`exceptional_end(at)` through the dispute adapter to the Agreement's dispute
authority. `at` is never future-dated: a pre-start failure journals immediately
and files at the Agreement start. The seller sends no stop or reverse of its own
on this path, so the authority receives the complete self-penalty package without
reconciling partial seller payment effects. End service owns the end and filing
journal, the evidence store retains the cause and the kept evidence, and an
uncertain filing outcome uses the same operation identity and read-and-retry
contract rather than a second correction journal.

Arkhai mediation's only mechanical ruling is the standard self-penalty
(`openspec/changes/agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`); its amounts and effects belong to mediation's published mapping, not to
this payment adapter, which derives the parts and terms the ruling reads — the rate
part it stops returned, the setup part it returns only for non-delivery, the penalty it
caps. An unsupported hosted bond is a publication refusal. A self-penalty is a
package of stop, refunds and the capped penalty, bond reserved; a partial seller
path would still need a dispute. Arkhai mediation records disputes so it can act
on bad sellers, banning included, and the buyer may still bring its own case.

The adapter consumes the foundation's `exceptional_end` dispute intent and
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

An on-demand refusal of `notice` identifies `exceptional_end` as the path for actual
seller non-delivery, not a self-interested override or an automatic filing on
refusal; a lawful end before disclosure keeps its cause without a seller-fault
filing. The foundation-owned VM admin interrupt route uses `notice` for a lawful
entitled stop and files `exceptional_end` through the dispute adapter for a
seller-caused emergency failure, spot hardware failure included. Alkahest splitter
execution and its defects remain outside this work.

### D6a. The rate buyer end preserves the priced notice

This change owns the rate buyer-end flow the foundation defers to it, in the neutral
buyer half and in both domains' canonical end verbs. A normal buyer end submits the
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
cooperative payment stop. The buyer's `buyer_end(at)` case and its handling are the foundation's
(`openspec/changes/agreed-evidence-and-early-termination/design.md#the-buyers-end`); this change supplies the stop-then-hint rate sequence it starts with.
Both-authorities-down recovery keeps the journal and retry path. The terms change owns the display of a normal stop against
an immediate surrender, and of billing that continues while a stop is pending.

**The buyer's watchdog.** The honest-crash exposure — the resource lost while the
seller's storefront is down, the buyer charged until its own stop lands (foundation
D12) — is bounded from the buyer's side by this change's watchdog in
`kit/deal-lifecycle-buyer`: once delivery is `available`, the buyer half probes the
disclosed access on a buyer-configured interval and, when the resource stops
answering for a configured number of consecutive probes, sends the buyer's ordinary
entitled stop and `hint` through the flow above, journaling the probe evidence it
acted on. It sends nothing the buyer could not send by hand, asks nothing new of the
authority, and turns "until the buyer notices" into one probe interval without seller
cooperation. What "stops answering" means is the access the storefront disclosed —
the VM's or bare-metal host's reachability on the disclosed address and credential
kind — not the buyer's workload; a probe failure is the buyer's observation (foundation
D9), kept with its instants, and the stop it triggers is reversible by nothing, so the
default interval and threshold are conservative and the watchdog is opt-in per deal.
The display names it as the buyer's lever and states that billing runs until the
stop lands.

### D7. Servicing declarations and identity rotation

The terms change owns the neutral servicing declaration, the publication and
acceptance doors, and the validation of the proposed profile; this change layers
the payments identity and mode checks on that validation at materialization and
refuses an absent declaration even for accepted-but-unmaterialized work.
Convergence owns rate startup, recovery and continuation registration; activation
owns the production switch-on after hosted deployment. Disabling new publication
never abandons materialized deals. Hosted enablement is a separate deployment gate.

The lane-only `proposed` declaration binds the fixture payments identity to the
configured `SERVICE_IDENTITY` in test mode (`livemode = false`). The
mechanism-specific materialization check layers on the neutral declaration
validation and refuses mismatched identities, live mode and production use; it
never queries private control or status routes to establish trust.

Configuration may list current and retiring service identities with retirement
dates. During the overlap an old receipt remains verifiable and a fresh snapshot
under the current identity re-anchors a running deal: the foundation verifier
accepts current and retiring identities with validity windows and a
caller-supplied minimum sequence, and the current snapshot attests its embedded
old receipt, whose binding to the persisted mandate, parties, mode and sequence is
verified. The re-anchored snapshot is stored durably as new approval evidence
before dependence on the retiring key is removed, and the original signed bytes
are kept for disputes. A stale or rolled-back snapshot cannot restore a retired
trust anchor.

The kit returns re-anchoring evidence for rate deals; convergence persists it and
reports unanchored rate deals. Re-anchoring is scoped to rate deals here. Once-only
hosted deals are included in the retiring-key dependency inventory and must drain
before removal; durable once-only re-anchoring is deferred, not assigned silently
to a rate-only consumer. A retiring key is removed only after running deals have
re-anchored or drained. No per-deal pin survives revocation, and a `livemode`
change cannot re-anchor and requires draining. This change owns rotation policy,
configuration and the adapter seam, not the cryptographic proof implementation.

### D8. Vectors, qualification and consumer scenarios

The three evidence classes are the lane double's, by name — *Qualification against
the published contract*, *Qualification against a proposed contract*, *Live
evidence* (its [D6](../add-arkhai-payments-lane-double/design.md#d6-lane-first-use-and-evidence-classes));
pinned-vector conformance is supporting evidence, not a fourth class. Results keep
the target identity and mode, hashes and the control trace. Only the external
service's own suite qualifies its ledger and payouts. Examples and fixtures use
`USD/6`; production reads the Agreement's asset.

| Scenario or prepared entry point | Executor | Evidence boundary |
|---|---|---|
| Derivation, authorize phases, the setup part, exceptional-end filing; adapter and vector targets | this change's focused kit suites | pinned-vector support; published conformance only for published bytes |
| Buyer stop and hint, seller preempt, setup and rate approval fixtures | this change's CLI and application first use | command mechanics against the named published or proposed contract |
| Delivered on-demand and spot, due-work barriers, release and access closure; the rate matrix | convergence | published or proposed qualification as the target permits |
| Hosted four-path qualification | activation | live evidence, from deployed authorities only |

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
lane double's typed control contract; this change produces kit, vector and
re-anchoring evidence and defines no parallel lane clock or progress rule.
Convergence alone owns the consolidated rate qualification matrix
([Scenarios and evidence](../converge-ongoing-compute-leases/design.md#scenarios-and-evidence)),
its runnable scenarios and their execution; this change prepares its entry points
— the rate and setup preset and approval fixtures, the typed buyer-end and seller
notice and preempt commands, the adapter `start` and read seams — and runs no lane
qualification of them. Physical completion evidence proves release and access
closure, not `lease_ended` intent alone. A prepared interim rate scenario,
on-demand included, names its buyer's explicit `started_period` acceptance for the
payee entitlement and any charged term end, keeping default-policy refusal and
returned-capable acceptance as distinct observations.

Published vectors qualify derivation and contract use here; proposed lanes never
prove hosted internals, and hosted prerequisites are reported before a scenario
runs. Activation lists the producer-published signed snapshot, start and reversal
vectors among the blockers to published qualification; double-generated traces
satisfy none of them and enable no published production servicing.

## Rejected alternatives

- A payee-advanced horizon or vouch: a dishonest seller can advance it; the buyer's own stop and a case over held money are the guarantee.
- Renewable site deadlines as buyer payment protection: the site and the storefront are both the seller; activation and renewal policy is a seller-value decision elsewhere.
- A required minimum spend, or a service request for one: churn is priced by setup or refused through seller policy.
- An extra `once` fee labelled a minimum: setup is additive, not usage drawdown.
- A backdated or effective-time payee stop: a past exceptional end is filed through the dispute adapter and mediation applies the standard self-penalty package.
- Local notice-stop scheduling: it dies with the storefront; pending stops belong at the authority.
- Claiming the on-demand mandate prevents physical seller preemption: the premature-stop penalty and the buyer's case over held money are the remedy, and the seller's own exit is the mechanically ruled self-penalty.
- A seller-side exceptional-end stop or reverse, explicit restitution entries, implicit favourable-payee stop privileges, a payee notice waiver, or a payer early release: `exceptional_end` is a dispute filing, not a partial payment path.
- A compound termination authority at payments — a transaction-level event ending billing at an authorized past time, settling rates `returned`, refunding `once` parts by unserved share and forfeiting a bond: deferred until hosted bonds are designed, and it would also need dispute-authority recording so terminations inform action against bad sellers. The foundation owns this record.
- A payer `start`, or a start at approval: `start` is the payee's responsibility after provisioning, and an early start is disputable.
- Reverse-before-stop as a safety rule: `afterStop` holds preserve reversal after a stop.
- An unsupported post-stop refund journal: reverse already works after a stop while money is held, and paid-out money is outside that primitive.
- Storefront cumulative-target end refunds: they bind only a cooperative seller, race independent authority rulings, and absorb unrelated discounts.
- Boundary-aligned seller notices as a substitute for `partialPeriod`: they change the offered notice and cannot encode an arbitrary committed treatment.
- Local final-period pricing: the payment term and the authority decide it, the explicitly charged interim preset included.
- A separate per-period mechanism or domain adapter: generic parts and authorities serve both domains.
- A new preemption route or an escrow-keyed admin verb: lifecycle `submit` is already the authenticated command boundary.
- Pinning accepting keys forever, or draining every deal on each rotation: a bounded overlap with re-anchoring preserves running deals without trusting revoked keys.
- Proposed qualification as live proof: a double cannot establish deployed authority behaviour.

## Dependencies and ownership

- `agreed-evidence-and-early-termination` (whole change): the codec and authority
  derivation, the vendored contract and verified snapshots (its round 2 owns the
  proof implementation, not duplicated here), the dispute intents and mediation's
  published self-penalty mapping, the activated-delivery envelope, and the
  rotation verifier's inputs. The seller never substitutes direct payment calls
  for the filing path; a spot emergency exit uses it rather than an extra stop
  entry.
- `negotiate-open-ended-compute-terms` (whole change): the agreed-price accessor
  and period unit, the listing bounds, the accepted pricing carrier (resize task
  2.1a), the option shape and start-identity rule, the servicing declaration, the
  whole-second start resolution before signature, and the publication and
  acceptance doors. The terms change owns generic publication emission through an
  injected preset-helper interface; this change supplies the hosted helper, the
  materialization door, and its payments identity and mode check. Convergence
  alone owns startup.
- The foundation's in-process contract fakes gate kit library integration; the
  runnable lane doubles gate lane evidence only, and no kit imports the double
  tooling.
- `converge-ongoing-compute-leases` depends on this change and on
  `unify-compute-delivery-path` as whole changes; it owns funding timers,
  persisted rate re-anchoring and the complete rate qualification matrix.
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
fixtures, and delivery fails closed without the rate hook: that proves a pending
authority stop, not a working delivered spot lease. Production rate publication
stays dark until its servicing doors are composed, and that fixture is not
production enablement.

## Status

Design, reconciled onto the lifecycle foundation on 2026-10-29 from the earlier
`settle-ongoing-compute-through-arkhai-payments` and
`publish-and-preempt-spot-compute` designs, which this change absorbs. Two review
rounds shaped it: the first fixed the whole-second start rule, the activated
evidence envelope's contents and the caller-owned journal comparison; the second
removed the seller
restitution entries and the cooperative storefront payment stop, kept `buyer_end`
as a person-ruled case and `end_delivery` as receipt-only evidence, and deferred a
compound payment termination until hosted bonds exist. The option shape,
zero-notice presets and the bare-metal setup rule follow Goal 8's fourth review
round with the owner.

Strict OpenSpec validation passes on the pinned 1.14.0; `make check-change` passes
apart from the citation of `openspec/specs/deal-lifecycle/architecture.md`, which
the foundation's closeout creates. No implementation, deployment or product
qualification is claimed.

## Design promotion record

Destinations are planned, not claims of implemented behaviour.

| Accepted decision | Permanent location |
|---|---|
| D1–D2 rate derivation, the setup part, presets and the exact check | `openspec/specs/settlement-servicing/spec.md`; `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| D3 external contract context | `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" |
| D4–D5 pure rate authorization, envelope consumption, operation identity, authority-priced `partialPeriod` and the journaled exceptional-end filing | `openspec/specs/settlement-servicing/spec.md` and `architecture.md` |
| D6–D6a seller notice, the rate buyer end and the CLI | `deal-lifecycle` `spec.md` (foundation-created; [delta](specs/deal-lifecycle/spec.md)) and `architecture.md`; `docs/development/ARCHITECTURE.md`, "Release" |
| D7 declarations and rotation | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/settlement-servicing/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D8 vectors and evidence classes | `openspec/specs/test-compatibility/spec.md` and `architecture.md`; `kit/arkhai-payments/README.md` |
| The adapter and continuation boundary | `docs/development/ARCHITECTURE.md`, "Kit areas" and "Settlement servicing" |
| Campaign and Goal 8 currency | `openspec/changes/README.md` and `docs/development/ROADMAP.md`, at design merge and again at closeout |
