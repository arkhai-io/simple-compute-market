# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against four rounds of independent design review of the
goal. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code and the service's vectors and adds the
spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `kit/arkhai-payments/src/market_arkhai_payments/models.py`, generated from the
  vendored schema, already has `RatePart{kind, asset, amount, period, reserveAhead,
  hold}`, `Hold = HoldFor | HoldUntilStop` ("collectable once the transaction is
  stopped"), `RateReservation`, `RateProgress{periodsEarned, grossEarned,
  reservedThrough}`, `PartSnapshot{held, released, reversed, reserved, refunded,
  rate, status}`, `TransactionSnapshot{transaction, observedAt, fundedThrough, stop,
  events, latestEventSequence, livemode, receipt, attachments}`,
  `TransactionStop{effectiveAt, cause, sequence, settled}` with `Cause ∈ payer |
  payee | authority | terms`, `TermsStopEvent`, `StoredEvent.sequence` (absent on
  legacy events), `LifecycleKind ∈ start | stop | reverse`, `Authorities{start, stop,
  reverse}`, `EventCommand{kind, part?, amount?, payload?}` with `payload` "recorded
  and never interpreted", and `SignedTransactionSnapshot{snapshot, proof}`. A mandate
  holds 1–64 parts. Nothing outside `models.py` reads any of `RatePart`,
  `fundedThrough`, `TransactionStop`, `latestEventSequence`, or `reserveAhead`. There
  is no transaction-level status; a stopped transaction is one whose `snapshot.stop`
  is present. `EventCommand` carries no effective time; `ApiErrorCode` includes
  `transaction_stopped`, `hold_matured`, `hold_not_reversible`,
  `insufficient_held_funds`, `request_id_reused`.
- `mandates.py`: `derive_mandate` emits one `once` part with
  `hold.for = ceil(start − accepted) + duration + window`, `expires = floor(accepted)
  + window`, authorities `start` and `stop` `[payer, payee]`, `reverse` `[payee,
  dispute_authority]`, nonce `arkhai.payments.v1`; `MandatePolicy` requires
  `duration_seconds` and a fixed `amount`; `PaymentsOptionParams` is
  `{payee_account, asset, window, deposit_agreement}` with `extra="forbid"`. The
  asset is the Agreement's, which must equal the option's — the kit checks the two
  copies agree (`mandates.py`, `settlement_config.py`), a pre-existing duplication
  this change leaves as it is; `USD/2` survives in the README, examples, and tests.
- `receipts.py`: `verify_receipt` checks the Ed25519 signature over the receipt
  frame, `livemode`, the transaction ID against the mandate, the deal hash, and the
  parties — not parts, amounts, holds, or rate. Nothing verifies
  `SignedTransactionSnapshot.proof`; `PaymentSellerStage._fully_reversed` is the one
  reader of snapshot part state, and it is unverified. A stored receipt is re-verified
  at restart against the current `service_identity` and `livemode`, which is why a
  rotation is a cutover that drains open deals (`DEPLOYMENT_AND_CONFIG.md`).
- `client.py`: `approve`, `get_transaction`, `poll` (until the transaction exists),
  `attach_agreement`, `ensure_agreement_attached`, `reverse` (idempotency key
  `reverse-{txid}`, reversing every still-held part). No `start`, `stop`, partial
  reverse, event read, or health call.
- `fixtures/payments_client.py`: `FakePaymentsClient` uses a placeholder proof,
  emits parts `held` or `reversed`, empty events, no `fundedThrough` or `stop`, and
  has no `stop`. `test-vectors/payments.json` has mandates (three `once`, one `rate`
  that is only hash-checked; none mixed), a receipt, attachments, approvals; no
  snapshot and no lifecycle event. `e2e-tests/settings.toml`'s `[payments]` target is
  blank by default, and every payment scenario skips without one. The double that
  replaces the fake is [`add-arkhai-payments-lane-double`](../add-arkhai-payments-lane-double/)'s.
- The mandate carries no start time; `Receipt.approvedAt` is the approval. The
  earlier proposal's contract notes say periods count from `start`, the first batch
  including any `once` parts is reserved at approval, and a payee stop may be
  backdated — the last of which is not in the vendored schema.
- `negotiation-driven-capacity-resize` §2, in implementation, makes the negotiated
  scalar a basis-point multiplier wherever an offering carries a resolvable rate
  structure, the quote `ceil(evaluate(rates, shape, duration) × bps / 10 000)`
  derived by each side; `negotiate-open-ended-compute-terms` D2 builds on it and
  supplies the one accessor this change prices from.

## Goals / Non-Goals

**Goals:** the kit can derive, verify, start, keep alive, stop, correct, and prove a
per-period transaction; what the storefront vouches for is the most a buyer can be
charged.

**Non-Goals:** any storefront or buyer behaviour; the listing terms; the in-lane
double, which is its own change; live qualification, which stays with the payments
service's own tests; a contract change to the service, which is recorded as this
repository's requirement and carried to the service's maintainers through the owner.

## Decisions

### D1. Per-period billing is an option param, and the mandate follows it

`PaymentsOptionParams` gains `period` and `reserve_ahead` (ISO durations, fixed
units as `window` is). An option stating both derives one `rate` part — `amount` the
per-period charge, `period`, `reserveAhead`, `hold: {until: stop}`; an option stating
neither derives one `once` part exactly as today; stating one without the other is a
publication blocker. `MandatePolicy` stops requiring a duration for a per-period
option. The buyer's `check` re-derives under its own policy as now, so an option the
buyer did not select cannot be billed per period.

The per-period charge is not read from `Agreement.amount`. It is the agreed price the
one accessor `negotiate-open-ended-compute-terms` D2 defines returns, with its unit:
for a per-period option the quote for one `period`, rounded upward as
`negotiation-driven-capacity-resize` requires; for a prepaid option the total for the
term, charged by the `once` part as today. The mandate derivation and the buyer's
check both call the accessor and nothing else, so a reader that would have to know
whether `amount` is a multiplier or a total never exists in this kit.

A per-period option may also state a **`minimum_spend`** — an amount in the option's
asset, or a count of periods at the rate — under which the buyer pays
`max(minimum, usage)`: the enforceable minimum cost of a lease, which a buyer's stop
cannot recover and which repeated provisioning therefore pays each time, the principle
Goal 5 records against free-to-mint identity. Its refund rule is a committed,
buyer-visible term in the params, not a discretion: reversed when delivery fails for
the seller's reasons or the buyer stops before the create is dispatched, kept after.
Deriving it needs the payments service to draw the rate part's usage down against a
prepaid part, which the published contract cannot express — a `once` part beside the
`rate` part is an *additional* fee, not a minimum — so `minimum_spend` is a required
capability in the requests below, and until it lands a per-period option states no
minimum and the churn vector is an accepted risk on VM; bare metal's per-period
options require it (`negotiate-open-ended-compute-terms` D13).

Example option params and derived part, at a per-hour quote of 2,500,000 `USD/6`:

```json
{"payee_account": "acct_seller_example", "asset": "USD/6", "window": "PT15M", "period": "PT1H", "reserve_ahead": "PT2H"}
{"kind": "rate", "asset": "USD/6", "amount": "2500000", "period": "PT1H", "reserveAhead": "PT2H", "hold": {"until": "stop"}}
```

*Rejected:* a separate per-period mechanism ID. *Rejected:* `amount` as the
per-period charge, and `PT1H` only (`negotiate-open-ended-compute-terms` D2).
*Rejected:* a `once` part beside the `rate` part named as a minimum — at $2.50/h with
one period stated it charges $5.00 for the first hour, an additional fee under a
minimum's name; an honestly named `initial_fee` was considered and set aside in
favour of the true minimum, which is what buyers recognise. *Withdrawn:* the earlier
floored derivation from an hourly `amount`; the resize change's upward rounding and
multiplier replace it.

### D2. `start` is the payee's; `stop` is both parties'

On a rate part the mandate authorizes `start` for `[payee]` and `stop` for `[payer,
payee]`, whatever the interruption policy; `reverse` stays `[payee, dispute
authority]`. One issuer of `start` means one instant at which billing can begin and
one party accountable for it: the storefront's `start` carries the delivery evidence
that made it lawful (D5), and the buyer's client records the instant it first
obtained the credentials and the instant the resource first answered, beside the
`start` event as read from the signed snapshot, as its evidence against a `start`
issued early (`converge-ongoing-compute-leases`, the buyer's record). The payee's stop
is the honest way to end billing when the seller must (a withdrawn resource, a
lease's end), and removing it from an on-demand mandate would remove only that.
"Won't preempt" is a promise in the Agreement's interruption terms, remedied through
`reverse` and dispute. A buyer who wants `stop: [payer]` written into the mandate may
ask for it as an option param in a later change; nothing here precludes it.

*Rejected:* `start` for both parties, a payer's `start` accepted as the deal's —
a buyer's client that starts at approval is billed before any resource exists, and
the delivery state machine would have two issuers to reconcile. *Rejected:* `start`
for the payer only, disclosure waiting for it — the buyer's consent as the start is
the strongest property for the buyer, but a provisioned resource then sits idle and
unbilled until the buyer acts or the activation deadline reclaims it, every buyer
client gains a protocol step, and the "resource does not work" case is a dispute
under either model. Revisit trigger: the service exposes no dispute path a
marketplace buyer can use, which would make evidence worth nothing and consent the
buyer's only protection.

### D3. `reserve_ahead` must cover polling plus teardown, and bounds the horizon

The reserved horizon is the only funds a seller can rely on between an exhaustion
and noticing it, so the kit refuses to publish an option whose `reserve_ahead` is
shorter than a floor the composing storefront passes it, and the floor is each
storefront's, derived from its real provisioning and teardown latency plus polling,
transport, and clock tolerance — never from the mock profile
(`converge-ongoing-compute-leases`). The same number bounds how far ahead the
storefront vouches for billing (D5), so it is the one buyer-visible bound on what a
dead storefront can cost: the option's `reserve_ahead` is shown as that bound.

### D4. A snapshot is evidence only once verified, bound, and ordered

One `verify_snapshot` beside `verify_receipt`, applied before any reader interprets a
snapshot, checks in order:

1. the proof against the pinned service identity over the snapshot's canonical
   frame, and `livemode` against the expectation — a `livemode: true` snapshot is
   refused outright when the composition's servicing declaration names the proposed
   contract (D10), whatever the expectation says;
2. the snapshot's `transaction` against the expected transaction ID, and its
   embedded receipt's deal hash and parties against the persisted mandate and
   Agreement, as `verify_receipt` does for a bare receipt;
3. the part structure against the mandate's parts — a `rate` part where one was
   derived, a `once` part where one was, nothing extra;
4. `observedAt` within a configured tolerance of local time, generous (minutes),
   since its job is to catch a replayed day-old snapshot rather than adjudicate
   skew;
5. `latestEventSequence` against a high-water mark the caller persists per deal in
   its continuation state (`converge-ongoing-compute-leases` D2), refusing a
   regression; a snapshot *at* the mark is accepted only if its `observedAt` is newer
   than the one recorded, and never advances the mark.

Freshness and sequence have distinct roles and neither replaces the other: a
replayed snapshot at sequence N passes the sequence check while the service has
accepted stop N+1, and funding state moves without a lifecycle event, so
monotonicity cannot prove currency; the sequence refuses known regression, freshness
bounds age, and local terminal state prevents resurrection. The hostile fixtures
include an equal-sequence stale snapshot, across a restart.

Every reader of `fundedThrough`, `stop`, `parts`, or `events` goes through it;
`_fully_reversed` moves onto it. An absent `fundedThrough` is "unknown" and
distinct from one in the past, and before the deal's `start` it is expected: the
contract does not say the horizon exists before the period clock runs, so the
pre-start evidence of funding is the embedded receipt's reserved first batch
(`ReceiptPart.rate.periodsReserved` covering `reserve_ahead`) and the absence of a
stop, and the horizon governs only after `start`. A pre-start snapshot vector is
asked of the service so that shape is confirmed rather than inferred. The vendored
vectors gain a snapshot vector, the fixtures a snapshot signer, and the companion's
"Snapshot proofs are not evidence" paragraph is replaced. The frame is confirmed
against the service's published vectors in this change's design session; if the
service publishes none, that is a blocker named in the index.

A receipt embedded in a snapshot whose proof verifies is trusted by that proof: its
fields are checked against the mandate and its own signature need not verify under
the current pin. This is what lets a running deal re-anchor across a service-identity
rotation (D7).

*Rejected:* freshness from the fetch alone — the stored snapshot a restart recovers
from is exactly the replayed one. *Rejected:* trusting only the event stream and
renewing to a fixed lead — it gives up `fundedThrough` as the renewal input.

### D5. The billing horizon, and the operations the kit exposes

**The horizon.** A rate part carries a `vouchedThrough` instant that only the payee
advances, with a `vouch {part, through}` event: monotonic, never past the
transaction's `fundedThrough`, refused on a stopped transaction. A period may begin
only while the current instant is before `vouchedThrough`; when the instant passes it
unadvanced, the service stops the transaction itself with cause `terms`, settled to
that instant. The storefront advances it each cycle to the earliest of now plus the
option's `reserve_ahead`, `fundedThrough`, and the agreed end, and renews the site's
lease to the same instant in the same cycle (`converge-ongoing-compute-leases` D2),
so billing and the physical lease lapse together, within one cycle, whatever happens
to the storefront. Nothing accrues that the storefront did not vouch for while alive.
This is the one capability the published contract lacks that the goal's guarantee
needs (the requests below); until it is vendored, per-period servicing is declared
only under the lane profile against the proposed contract (D10), and the double
implements the extension (`add-arkhai-payments-lane-double`).

**The guarantee it keeps.** *Charges after a deal's effective end are reversed
before they are collected*, with one bounded residual stated on every buyer-facing
surface: a buyer may be charged for at most `reserve_ahead` past an end the
storefront did not observe — the time between a site's withdrawal and the horizon
lapsing while the storefront is dead. With an effective-time payee stop (welcome, not
required) even that case needs no correction where the storefront knows the instant.

**The operations.** `start(transaction, operation, evidence)`, `vouch(transaction,
part, through)`, `stop(transaction, operation)`, `reverse(transaction, operation,
part, amount)`, and `refund(transaction, operation, part, amount)` post the
corresponding `EventCommand` with idempotency keys `{kind}-{operation}`, where the
operation is the identity of an entry in the caller's financial operation journal
(`converge-ongoing-compute-leases` D5): immutable once written, with its amount and
part, so a retry resends the same command under the same key and a later correction
is a different operation with its own. `vouch` is not journaled per cycle: it is
idempotent and monotonic, and the caller records the last instant it vouched in its
continuation state before the call. A `start` is refused by the kit unless the
caller supplies the delivery evidence that made it lawful — the commit acknowledged
and the dispatch begun — which is stored with the operation. The existing
whole-transaction `reverse` keeps its `reverse-{txid}` key for refunds of prepaid
deals. A `transaction_events(transaction)` read returns the verified snapshot's
events so a caller resolves what it already sent.

**Reverse before stop, always.** On learning of an end the caller reverses the
excess — every charged period whose start is at or after the effective end — while
the funds are held, and stops only once the reverse is acknowledged. The horizon is
what makes this order safe: a crash between the two no longer leaves an unbounded
tail, because the service stops at `vouchedThrough` on its own. A correction that
becomes due *after* the stop — the dead-storefront case above, where the site's
`lease_ended` arrives on resume after the periods were released — is journaled as a
`refund` and carries the outcome `unsupported` while the service has no such command:
retryable on every cycle, never terminal, so it drains the day the capability lands
and the record shows what is owed meanwhile.

**Refusals, classified.** From the service's codes: `hold_matured` means the funds
left `held`, so the `reverse` is closed as superseded and re-journaled as a `refund`
of the same amount; `insufficient_held_funds` is a partial acknowledgement for the
amount the snapshot shows reversed, the remainder re-journaled; `hold_not_reversible`
and `request_id_reused` with a different payload are permanent, surfaced to the
operator; `transaction_stopped` on a `stop` is an acknowledgement, on a `start` the
undelivered path; transport failures and server errors are retries.

A future-effective stop needs no service support: the caller durably schedules it
and issues an ordinary immediate `stop` at the instant. The arithmetic of an excess —
half-open interval, a period charged iff it starts before the end, the started
period charged in full for a buyer-caused end and reversed for a seller-caused one —
is the caller's (`converge-ongoing-compute-leases` D5).

*Rejected:* keying by the decision — a second correction under the same key is a
replay or a conflict, and a fresh key carrying a recomputed total over-refunds.
*Rejected:* two required capabilities, an effective-time payee stop and a post-stop
refund entitlement — the second cannot reach funds the payee has withdrawn through
the service's own surface, so the guarantee would still have needed a settlement
hold or a narrowed scope; the horizon makes the storefront's silence end billing
instead of prolonging it. *Rejected:* no post-stop correction at all — it would make
the welcome refund capability unusable if it lands. *Rejected:* never stopping until
the site's report is reconciled — it cannot cover the dead storefront, which is the
only case left. *Rejected:* assuming payee backdating, or an effective time in
`payload`.

### D6. The period clock runs from the `start` event

The mandate has no start time; approval reserves the first batch; the first period
begins at the `start` event, which the payee issues. This is what lets a storefront
begin billing at verified delivery and not at approval, and what the reconciliation
of an approved-but-undelivered deal relies on: no period started, so a `stop` returns
the reserved batch, the minimum spend excepted under its committed refund rule (D1).
The service refuses `start` on a stopped transaction (`transaction_stopped`), which
the caller's delivery gate treats as the final check. Confirmed against the service's
conformance vectors in design; the double implements the same.

### D7. Identity rotation re-anchors running deals rather than draining them

This change is the one owner of rotation; `converge-ongoing-compute-leases` composes
it and adds nothing. The configuration may list a retiring service identity beside
the current one with its retirement date, the shape `service-identity-signing` uses
for marketplace principals. During the overlap a stored receipt signed by the
retiring key still re-verifies and a fresh snapshot signed by the new key verifies.
A running deal re-anchors on the first snapshot it verifies under the new key: that
snapshot, stored as the deal's evidence of approval in place of the bare receipt,
vouches for the embedded receipt (D4), and the deal needs the retiring key for
nothing after that. System status reports deals not yet re-anchored; when none
remain the retiring identity is removed, and only stragglers are drained. `livemode`
cannot be re-anchored — a test-mode deal cannot become a live one — so a mode change
stays the drain the runbook describes. Seller credentials need no design: they are
read at each call, and an unavailable one is a transient the caller treats as
"cannot verify". The acceptance scenario is one deal running across a rotation
window in the double.

*Rejected:* pinning the accepting identity per deal, which trusts a revoked key for
as long as the deal runs.

### D8. Platform credits are `USD/6`

Examples, README, and fixtures move to `USD/6`. No production code names an asset;
the mandate's asset is the Agreement's.

### D9. The double is its own change

The in-lane HTTP double of the service — the published contract and the proposed
horizon extension, with hostile controls — is
[`add-arkhai-payments-lane-double`](../add-arkhai-payments-lane-double/), which this
change depends on so that every operation here is tested against it from the first
round. The double implements the snapshot frame this change verifies; the two are
reconciled against the service's published vector in this change's design session.

### D10. The composition declares servicing, naming the contract it is built against

The registration gains a capability, declared by the composition, that it runs the
per-period continuation, carrying the contract it services: `published`, which no
composition may declare until the horizon is vendored
(`activate-per-period-compute-servicing`), or `proposed`, which is accepted only when
the configured payments endpoint is the double and is refused by startup in any
other configuration; under `proposed`, D4 refuses every `livemode: true` snapshot.
`negotiate-open-ended-compute-terms` D9 publishes and accepts per-period options only
where servicing is declared; this change adds the third door: **settlement
materialization refuses to derive a rate-part mandate for a composition that does
not declare servicing**, which can be reached only by a deal accepted under a
declaration since withdrawn, and which the startup rule
(`converge-ongoing-compute-leases` D9) already makes a refusal to start. The three
checks are one invariant with two outcomes: a per-period selection is serviced, or
refused at the first door it reaches.

Evidence produced under `proposed` is recorded as *qualification against a proposed
contract*, a named evidence class distinct from live evidence, which only the
activation follow-on produces.

### D11. What the buyer's client keeps

Beside the snapshot verification the buyer already does, `core/buyer` records for a
per-period deal: the instant it first obtained the credentials, the instant the
resource first answered, the `start` event and its sequence as read from the signed
snapshot, and the signed `lease_ended` the storefront's status read returns once it
has it (`buyer-initiated-compute-termination` D6). The gap between delivery and
`start` is the buyer's dispute evidence; the site's event is its evidence of when the
lease ended. All of it is kept under the retention rule `buyer-initiated-compute-termination`
D4 sets, by the buyer's own client, so neither side's evidence depends on the
other's honesty.

## Requests to the payments service

Recorded here as this repository's requirements, in the order they matter to it.
They reach the service's maintainers through the owner, as part of the reconciliation
between this goal's design and the service's own in-flight contract revision, rather
than as a standalone request.

1. *Required capability:* the billing horizon (D5) — `vouchedThrough` on a rate
   part, a payee-only `vouch {part, through}` that is monotonic and never past
   `fundedThrough`, periods beginning only inside it, and a lapse that stops the
   transaction with cause `terms` settled to the lapsed instant; a vector of a
   running rate part vouched, lapsed, and stopped by the service. The first question
   for the maintainers: whether a lapsed payee-supplied horizon can stop a
   transaction without a payee-issued event under the service's billing model; if
   not, the effective-time stop below with a settlement hold is the fallback.
2. *Required for one feature:* a true minimum spend (D1) — a prepaid part that usage
   on a rate part draws down, so the payer pays `max(minimum, usage)`.
3. *Confirmation and vector:* the pre-start snapshot's shape — whether
   `fundedThrough` is populated from the reserved batch before `start` (which would
   collapse D4's pre-start branch), and what the receipt's reserved parts carry.
4. *Confirmations and vectors:* the snapshot proof's frame (D4); the period clock
   from `start` and `start` refused on a stopped transaction (D6); a mandate mixing
   `once` and `rate` parts.
5. *Questions:* how a payer raises a dispute on a rate part's `start`, and what
   evidence the service expects (D2, D11); the service's dispute horizon as a
   published value, which the retention floor must exceed
   (`buyer-initiated-compute-termination` D4).
6. *Welcome:* an effective time on a payee stop, at or before receipt, which removes
   the residual of D5 wherever the storefront knows the instant; a refund of a
   stopped rate part's released funds to the payer, idempotent by request identity,
   which is what the `refund` journal kind drains into; a prorated final period on a
   rate part; periodic collection of a running rate part's earned periods by the
   payee.

## Open questions

- Whether the kit's `vouch` and the site's renewal are issued from one cycle step
  with one recorded instant, or two steps with two; settled in
  `converge-ongoing-compute-leases`' design, the former preferred.
- The option-param shape (D1) is frozen in this change's design session before
  `negotiate-open-ended-compute-terms`' runs; `minimum_spend` is in it, inactive until
  the service capability lands.

## Implementation cadence (recommended)

Two rounds. Round 1: option params, rate-part derivation through the accessor,
authorities, snapshot verification with vector and fixture, the servicing capability
with its contract value and the materialization rule, `USD/6`. Round 2: `start` with
its evidence, `vouch`, `stop`, `reverse`, `refund`, the refusal table, the events
read, and rotation, each proven against the double's controls. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2, D6 | `openspec/specs/settlement-servicing/spec.md` |
| D5 | `settlement-servicing` spec and architecture companion (the horizon, the guarantee and its residual, the ordering rule, the refusal table) |
| D3, D10 | `openspec/specs/settlement-configuration/spec.md`; `test-compatibility` spec (the evidence class) |
| D4 | `settlement-servicing` architecture companion (replacing its snapshot paragraph) and spec |
| D7 | `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" |
| D8 | kit README; `DEPLOYMENT_AND_CONFIG.md` |
| D11 | `buyer-orchestration` spec |
