# Design

## Context

The lifecycle foundation, [`agreed-evidence-and-early-termination`](../archive/2026-11-03-agreed-evidence-and-early-termination/),
is the frame: the protocol ends at commitment, and everything after it is
authority records and the signed bytes each party keeps. The terms a deal
carries — `early_termination {version, entitlements, settles_through,
premature_stop_penalty?}` and `adjudication` — live under the selected option's
`lifecycle`, beside its `price` and `settlement`. Payment derivation consumes that
shared codec; it keeps no mechanism-specific copy of the terms.

The vendored payments contract (`kit/arkhai-payments/schema/SOURCE.md`) publishes
every primitive this design uses: per-part authorities with a payee-only `start`,
stop entries `{account, notice, partialPeriod}` whose treatment is `charged`,
`returned`, `prorated` or the dispute authority's `chosen`, a part `end` that
always carries its own `partialPeriod`, `maxHoldExtension`, case extensions with
`lift`, and both `afterStop` and `for` holds. There is no unpublished candidate.

Goal 8's MVP changes land before this one. `derive-rate-parts-in-the-payments-kit`
derives rate parts under charged treatment only, checks them for the buyer, and
supplies the stateless rate adapter (start, entitled stop with notice, reverse,
immutable operation descriptors and refusal classification), verified rate
observations, the pure `authorize` hook and the materialization gate.
`serve-running-rate-deals-on-vm` composes them in the VM storefront and adds the
seller's notice command and `deals preempt`, the buyer's rate end, the VM admin
route's notice and the lane's test-mode declaration. `offer-per-period-vm-terms`
publishes fixed-shape, flat-priced VM options whose Agreement amount is an
absolute per-period price, behind a servicing declaration that lists `[charged]`.
This design extends those surfaces; it does not restate them.

Both compute domains are in scope. API credits stays on `once` parts. The adapter
is mechanism-owned and stateless; the caller's journal and continuation state live
in `kit/deal-servicing`, extended by
[`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/).

## Decisions

### D1. Presets: treatments, setup and the penalty

Prices come from the agreed-price accessor; the kit never reads the negotiated
scalar directly. The accessor owns its readings and their inputs: the MVP's
absolute per-period reading needs nothing beyond the selected option, and the
multiplier reading's accepted rate-structure carrier is
`negotiation-driven-capacity-resize`'s input to the accessor, not a gate of this
change. Both sides derive the same parts from the selected immutable option.

**Treatments by declaration.** The composition's servicing declaration lists the
partial-period treatments it has qualified (the terms change owns the contract;
the MVP's VM declaration is `[charged]`). Derivation admits a treatment only when
the declaration lists it, and refuses the rest, so lifting the MVP's charged-only
refusal is per composition and per treatment, never global. Once a composition
declares `returned`, its shipped presets carry `last_boundary` on the payee
entitlement and at the term end; the payer entitlement keeps `started_period`
with zero notice. Each changed preset is a new option ID, and deals made under
earlier presets keep their terms.

**Setup.** An optional `setup_amount`, a positive integer minor-unit string in the
option's asset, adds a `once` part before the rate; omission means no setup part.
It is an additional charge, not `max(setup, usage)`, visible before approval and
bound into the option ID. VM presets carry no setup part by default: a VM seller
opts in with a configured price. Bare-metal presets require a seller-priced setup
part, since provisioning a host is the cost churn imposes; the helper refuses an
incomplete configuration rather than inventing an amount. Churn beyond the setup
charge is the seller's to price differently or refuse through its negotiation
policy; neither domain has a required minimum spend.

Setup is owed from approval because commitment triggers provisioning. A payment
stop alone does not reverse it, and lawful preemption after delivery leaves it
earned. A qualified delivery_end reverses setup iff delivered=false, for either
cause, and keeps it iff true; site activation is not that fact. "For either cause"
generalizes the filer, not the ground: setup returns only when the seller never
delivered — by the seller's own filing, by its signature on the buyer's claim, or
by a person ruling delivered=false on the buyer's evidence — and a buyer's stop,
with or without a claim the seller does not sign, keeps it with the seller. The
buyer is told before approval that the setup charge is kept if it stops and
returns only when the seller never delivered. Parties file or concur through the
dispute adapter, with no seller direct payment correction.

The setup part's end is encoded at the Agreement start so mediation recognizes
it; payments clamps an end at or before approval to approval without changing
mandate bytes, so its effective end is max(Agreement start, approval). Like every
part end it carries a `partialPeriod`, which has no effect on a `once` part.
Setup-bearing presets stay disabled until a hosted dispute authority is qualified
on the vendored delivery_end revision (deal-lifecycle's "Setup returns by
delivered for either cause"); a setup charge is never published without its
remedy.

| Preset | Parts | Entitlements, once `returned` is declared |
|---|---|---|
| On-demand, VM | time rate; setup `once` only by seller opt-in | payer `{notice_seconds: 0, settles_through: started_period}`; no seller stop entry; term end `last_boundary` |
| Spot, VM | time rate; setup `once` only by seller opt-in | payer as on-demand; payee with its priced notice and `last_boundary`; term end `last_boundary` |
| On-demand and spot, bare metal | seller-priced setup `once` + time rate | as VM |
| Reserved | `once` for the committed term | existing `once` semantics |

**Penalty.** Both recurring presets may carry the foundation's
`early_termination.premature_stop_penalty`; the preset helper encodes only the
value the terms change resolves from its preset default and the seller's override.
An entitled notice stop pays none; a seller's exit without notice files
`delivery_end` and pays the capped penalty after the refunds. The buyer acceptance
policy — which by default refuses charged treatment on a payee entitlement and at
the term end, accepts it on the payer's stop, and displays a penalty without requiring
one — is the terms change's; this change consumes it. Once `returned` is declared, the
shipped on-demand and spot presets name `last_boundary` on the payee entitlement and at
the term end, and keep `started_period` on the payer's stop.

No class flag is persisted or used for dispatch. One pool may publish on-demand and
spot at different rates.

### D2. Per-part derivation beyond the MVP

The MVP derives the rate part's amount, period, reserve-ahead, absolute end,
`afterStop` hold, `maxHoldExtension` and authorities under charged treatment. This
change adds:

- **Treatments.** `end.partialPeriod` and each entitlement's stop-entry treatment
  come exclusively from `settles_through` through the foundation codec —
  `started_period` ↔ `charged`, `last_boundary` ↔ `returned`, `stop` ↔ `prorated` —
  admitted per declared treatment (D1). With S = 10, P = 60 and end = 120 under
  `returned`, the part charges [10, 70), returns the incomplete [70, 130) period,
  and delivery still ends at 120: a late start never bills past the agreed
  maximum, and maximum terms are not rounded down.
- **Setup.** Parts are ordered deterministically: setup when present, then rate.
  Setup uses the foundation's `once` permissions and its encoded end, without rate
  start or period arithmetic.
- **The payout hold.** The default hold is the foundation's: until the part's stop
  plus the dispute window, `{afterStop: dispute_window}`. Where the accepted
  option states a shorter payout hold — a seller-chosen, buyer-visible lifecycle
  term the codec owns and the option ID binds — the rate part derives
  `{for: <that hold>}`, releasing each period's earnings that long after it is
  earned. The terms change owns the term and its display as reduced protection;
  this change owns the derivation and the buyer's check.
- **The dispute entry.** The dispute authority's rate stop entry is
  `{account, notice: PT0S, partialPeriod: chosen}`, under which a ruling's stop
  carries its own treatment. If the MVP ships the fixed `charged` fallback, that
  treatment is bound into the option's settlement parameters; restoring `chosen`
  is then a new option with a new ID, and running deals keep their mandates.

Seller stop entries exist only for accepted entitlements: on-demand has none, spot
has its priced notice entry. An exceptional end grants no seller stop entry or
implicit payment privilege: the seller files a dispute and mediation acts under its
own entry. There is one notice per entitled party, the accepted entitlement's
`notice_seconds`; seller polling, watchdog and teardown budgets are operational
recommendations, not a payment term. Reserve-ahead does not replace the priced
payer notice, since unearned reservations return on a stop.

The buyer re-derives and checks every part, their order, authorities, notices,
treatments, holds, end, cap, asset and amount before approval. A changed listing or
configuration cannot alter an accepted mandate.

### D3. External contract context

An entitled stop takes effect at `max(at ?? now, now + senderNotice)` at
authority receipt and is never backdated. There is no implicit role-based or
buyer-favourable stop privilege, no payee waiver of payer notice, and no payer
early-release waiver. The earliest pending stop wins and cannot be withdrawn.

Per-part snapshots expose `started`, `stop`, `pendingStop`, `extensions` and
`releaseAt`. No rate accrues before the payee's `start`. Periods stay reserved,
not earned, until the period ends or the part stops, and a stop applies its
entry's `partialPeriod`; no started-period clawback is needed. With `afterStop`
holds this earning rule does not change payout; with `for` holds it moves period
payout one period later than earning at period start would. Exhaustion stops every
co-funded part at `fundedThrough` with cause `terms`; a part's `end` stops it with
cause `terms` even if no party acts.

Each earned amount stays held until its hold matures. An accepted case extension
covers current and later earnings, capped from each amount's normal release by
`maxHoldExtension`. A stop does not release money under an open extension. Partial
reverse works before and after a stop while money remains held. Only the dispute
authority opens case extensions and applies ruling effects, then lifts that case's
refs.

These are external dependencies, not behaviour SCM can implement by asserting it in
a normative spec. The vendored vectors include signed before- and after-start
snapshots, term-end and clamped setup-and-rate snapshots, and partial reversals
while running and after a stop. Two gaps remain, recorded as qualification limits
rather than closed by a double: the producer's own HTTP qualification covered
fixed payer and payee treatment only, not `chosen`, end or reverse; and the
stop-retry vectors are fixed-clock fixtures, not a real lost HTTP response.

### D4. Adapter additions

The MVP's adapter owns command translation, stable per-part request identities,
immutable operation descriptors, refusal classification and the pure `authorize`
hook (`derive-rate-parts-in-the-payments-kit`). This change adds:

- **Rate-part extension observation.** Verified per-part extension refs,
  `releaseAt` and money held under an open extension, exposed to lifecycle `read`
  and `watch` as the once adapter exposes them for `once` parts.
- **Matured-shortfall resolution.** The MVP reports `hold_matured`. Here the
  adapter surfaces the shortfall and the case path for the target no longer
  locally achievable, not an endlessly retried refund. No post-release refund
  command or journal kind exists.
- **Treatment observation.** A verified stop record carries its applied
  treatment, including a `chosen` ruling's, and the adapter reports it without
  computing a compensating delta.

The adapter has no database and no daemon and imports neither `kit/deal-servicing`
nor either domain.

### D5. Started-period treatment is enforced by the payment authority

| SCM value | Payment `partialPeriod` | In-progress period |
|---|---|---|
| `started_period` | `charged` | charged in full |
| `last_boundary` | `returned` | billing ends at the last boundary |
| `stop` | `prorated` | billed to the effective stop time |

The payments service computes this price; SCM does not. Negotiation decides the
accepted treatment; presets offer it (D1) and the terms-owned buyer policy accepts
or refuses it. The seller self-penalty is a separate mediation package whose rate
stops are always `returned`, on-demand included.

For authority start S and period P, periods are half-open [S + kP, S + (k+1)P). At
E = S nothing is earned. With S = 0, P = 60, A = 100 and E = 60 all three
treatments charge 100; at E = 61, `charged` keeps 200, `returned` keeps 100, and
`prorated` bills to 61 using the published contract's minor-unit rounding, which
is a qualification gate rather than SCM's own rounding.

| Winning record | Treatment |
|---|---|
| Payer or payee stop | that authority entry's `partialPeriod` |
| Exhaustion (terms) | the `fundedThrough` boundary; no partial period |
| Absolute part end (terms) | the end's own `partialPeriod` |
| Seller `delivery_end` | filed through the dispute adapter; mediation's mechanical self-penalty stops rates now with `returned` and reverses unserved earnings and `once` shares; no seller payment calls |
| `end_delivery` receipt | evidence of surrendered service only; the buyer half journals and retries its own stop |
| Dispute-authority stop or effects | the treatment the stop event carries under the `chosen` entry |
| Superseded or equal-time competing request | the authority's recorded winning stop and entry, never local arrival order |
| Unknown cause or ambiguous winning entry | an unsupported or unknown state; no inferred monetary action |

Independent discounts and ruling penalties are separate effects: SCM neither
absorbs them into end pricing nor computes a cumulative target.

Seller-caused unentitled ends use the foundation's journaled
`delivery_end(cause=payee)` through the dispute adapter to the Agreement's dispute
authority; the seller sends no stop or reverse on this path. Arkhai mediation's
cause=payee branch is the standard self-penalty
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`);
its amounts and effects belong to mediation's published mapping, not to this
adapter, which derives the parts and terms the ruling reads — the rate part it
stops returned, the setup part it returns only for non-delivery, the penalty it
caps. A rate deal whose dispute entry carries the fixed `charged` fallback cannot
receive the returned stop, so the standard package is qualified only on deals
whose dispute entry is `chosen`.

### D6. Seller notice beyond the MVP

The MVP supplies the negotiation-keyed notice command through lifecycle `submit`,
the authority-hosted pending stop, `pendingStop` in `read` and `list`, and VM's
`deals preempt`. This change adds bare metal's `deals preempt` through the same
typed client, and, once the exceptional-end observation is qualified, changes the
on-demand refusal of `notice` to name `delivery_end` as the path for actual seller
non-delivery, in place of the MVP's operator procedure. The VM admin interrupt
route, which the MVP delegates to `notice`, files `delivery_end` through the
dispute adapter for a seller-caused emergency failure, spot hardware failure
included. Alkahest splitter execution remains outside this work.

### D6a. The buyer's end beyond the MVP

The MVP supplies the neutral buyer half's stop-then-hint rate end and VM's
canonical end verb. This change re-drives bare metal's canonical end verb onto it.

**The buyer's watchdog.** The honest-crash exposure — the resource lost while the
seller's storefront is down, the buyer charged until its own stop lands — is
bounded from the buyer's side by a probe loop in `kit/deal-lifecycle-buyer` that
the buyer's own `buy` command runs in the foreground. There is no buyer daemon.
With the opt-in flag, the `buy` command does not return after delivery: once
`available`, it probes the disclosed access on the configured interval and, when
the resource fails a configured number of consecutive probes, sends the buyer's
ordinary entitled stop and `hint`, journals the probe evidence it acted on, and
exits. It exits also when the deal ends by any other path, or when the buyer stops
it. The opt-in, interval and threshold are persisted per deal in the buyer's
profile, so `buy --resume` re-enters the loop after a restart where the deal is
still running; the deal read shows `monitored`, `stopped` or `unmonitored`, and a
deal whose monitor is not running is shown as unmonitored, never as protected. The
probe is injected per domain — the VM's or bare-metal host's reachability on the
disclosed address and credential kind — so the kit learns no credential format.

The bound is conditional and stated as one wherever the watchdog is described:
detection takes at most `interval × threshold + probe timeout` after the loss, and
only while the monitor runs; the stop's acknowledgement and any priced notice come
after that, and billing runs until the stop lands. A probe failure is the buyer's
observation, and the stop it triggers is irreversible, so the default interval and
threshold are conservative. The watchdog sends nothing the buyer could not send by
hand.

### D7. Identity rotation

The MVP drains running deals before the payments signing key retires. This change
lets running rate deals survive a bounded overlap; its retention windows follow the
payments service's key-retention commitment.

Configuration may list current and retiring service identities with retirement
dates. During the overlap an old receipt remains verifiable and a fresh snapshot
under the current identity re-anchors a running deal: the foundation's verifier
accepts current and retiring identities with validity windows and a
caller-supplied minimum sequence, and the current snapshot attests its embedded
old receipt, whose binding to the persisted mandate, parties, mode and sequence is
verified. The re-anchored snapshot is stored durably as new approval evidence
before dependence on the retiring key is removed, and the original signed bytes
are kept for disputes. A stale or rolled-back snapshot cannot restore a retired
trust anchor.

The kit returns re-anchoring evidence for rate deals; convergence persists it and
reports unanchored rate deals. Once-only hosted deals are included in the
retiring-key dependency inventory and must drain before removal. A retiring key is
removed only after running deals have re-anchored or drained. No per-deal pin
survives revocation, and a `livemode` change cannot re-anchor and requires
draining. This change owns rotation policy, configuration and the adapter seam,
not the cryptographic proof implementation.

### D8. Vectors, qualification and consumer scenarios

Evidence carries one of the two labels the archived lane double defines
([its D3](../archive/2026-11-10-add-arkhai-payments-lane-double/design.md#d3-one-contract-per-double-and-two-evidence-classes)):
lane-double evidence, or live evidence, which only a hosted target yields.
Pinned-vector conformance is supporting evidence. Only the external service's own
suite qualifies its ledger and payouts.

| Scenario or prepared entry point | Executor | Evidence boundary |
|---|---|---|
| Treatments, setup, payout hold, dispute entry, extensions, matured shortfall, self-penalty observation, re-anchoring | this change's focused kit suites | vector conformance and the in-process engine |
| Bare-metal preempt and buyer end; setup and treatment preset fixtures; the watchdog | this change's CLI and application first use | command mechanics against the doubles |
| Delivered rate deals beyond the MVP's four VM rows, in both domains; ruling execution in the mediation double | convergence | lane-double evidence |
| Hosted qualification of what this change adds | activation | live evidence |

Unit and vector targets prove derivation, `partialPeriod` edges and exact event
bytes. Kit library integration uses the clock-injected payments engine in
`kit/arkhai-payments`' fixtures directly; HTTP doubles serve lane qualification
only. The MVP's four VM lane rows are `serve-running-rate-deals-on-vm`'s;
convergence alone owns the consolidated rate matrix
([Scenarios and evidence](../converge-ongoing-compute-leases/design.md#scenarios-and-evidence))
and its execution. This change prepares entry points and runs no lane
qualification of them.

## Rejected alternatives

- A payee-advanced horizon or vouch: a dishonest seller can advance it; the buyer's own stop and a case over held money are the guarantee.
- A background buyer service to run the watchdog: the `buy` command stays in the foreground instead, and the bound is stated as conditional on its running.
- Renewable site deadlines as buyer payment protection: the site and the storefront are both the seller.
- A required minimum spend, or a service request for one: churn is priced by setup or refused through seller policy.
- An extra `once` fee labelled a minimum: setup is additive, not usage drawdown.
- A backdated or effective-time payee stop: a past exceptional end is filed through the dispute adapter.
- Local notice-stop scheduling: it dies with the storefront; pending stops belong at the authority.
- Claiming the on-demand mandate prevents physical seller preemption: the penalty and the buyer's case over held money are the remedy.
- A seller-side exceptional-end stop or reverse, explicit restitution entries, implicit favourable-payee stop privileges, a payee notice waiver, or a payer early release: `delivery_end` is a dispute filing, not a partial payment path.
- A compound termination authority at payments: deferred until hosted bonds are designed; the foundation owns this record.
- A payer `start`, or a start at approval: `start` is the payee's responsibility after provisioning.
- Lifting the charged-only refusal globally: a treatment is offered only where its composition has qualified it.
- Changing a running deal's dispute-entry treatment in place: it would break re-derivation of the approved mandate; a new treatment is a new option.
- Storefront cumulative-target end refunds: they bind only a cooperative seller, race independent rulings, and absorb unrelated discounts.
- Boundary-aligned seller notices as a substitute for `partialPeriod`: they cannot encode an arbitrary committed treatment.
- Local final-period pricing: the payment term and the authority decide it.
- A separate per-period mechanism or domain adapter: generic parts and authorities serve both domains.
- Pinning accepting keys forever, or draining every deal on each rotation: a bounded overlap with re-anchoring preserves running deals without trusting revoked keys.
- Double-backed qualification as live proof: a double cannot establish deployed authority behaviour.

## Dependencies and ownership

- The archived foundation: the codec and authority derivation, the vendored
  contracts, the delivery_end intent and signing, the evidence stores and the
  identity-history verifier.
- `derive-rate-parts-in-the-payments-kit`: rate derivation under charged
  treatment, the buyer's check, the rate adapter, observations, `authorize` and the
  materialization gate; and, if the charged dispute-entry fallback ships, its
  binding into the option's settlement parameters.
- `serve-running-rate-deals-on-vm`: VM composition, the seller notice and VM
  `deals preempt`, the buyer's rate end, the VM admin route's notice and the lane
  test-mode declaration.
- `offer-per-period-vm-terms`: the VM presets and the permanent deal-lifecycle
  partial-period rules stated per declared treatment.
- `negotiate-open-ended-compute-terms`: the servicing declaration's treatment
  list, the buyer acceptance policy, the penalty and payout-hold terms and their
  display, the preset-helper interface and bare metal's publication.
- `converge-ongoing-compute-leases` depends on this change; it owns funding
  timers, persisted re-anchoring, the mediation double's ruling execution and the
  consolidated matrix. `activate-per-period-compute-servicing` owns hosted
  qualification.

## Status

Design, reconciled onto the lifecycle foundation on 2026-10-29 and rescoped
onto Goal 8's MVP changes on 2026-11-10, which took the reduced forms of its
rate mechanics, notice, buyer end and lane declaration. No implementation,
deployment or product qualification is claimed.

## Design promotion record

Destinations are planned, not claims of implemented behaviour.

| Accepted decision | Permanent location |
|---|---|
| D1 presets by declared treatment, setup and the penalty | `openspec/specs/storefront-publication/spec.md` and `architecture.md`; `openspec/specs/settlement-configuration/spec.md` |
| D2 treatments, setup, payout hold and dispute entry in derivation | `openspec/specs/settlement-servicing/spec.md` |
| D3 external contract context | `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" |
| D4–D5 adapter additions and authority-priced treatment | `openspec/specs/settlement-servicing/spec.md` and `architecture.md` |
| D6–D6a bare metal's notice and buyer end, the on-demand refusal and the watchdog | `openspec/specs/deal-lifecycle/spec.md` and `architecture.md` |
| D7 rotation | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/settlement-servicing/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D8 vectors and evidence labels | `openspec/specs/test-compatibility/spec.md`; `kit/arkhai-payments/README.md` |
| The adapter and continuation boundary | `docs/development/ARCHITECTURE.md`, "Kit areas" and "Settlement servicing" |
| Campaign and Goal 8 currency | `openspec/changes/README.md` and `docs/development/ROADMAP.md`, at closeout |
