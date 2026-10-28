# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against three independent design reviews of the goal. This
change's own design review may reopen any of them with a finding; its design session
verifies them against the code and the service's vectors and adds the spec deltas.

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
  `{payee_account, asset, window, deposit_agreement}`. The asset is the Agreement's,
  which must equal the option's; `USD/2` survives in the README, examples, and tests.
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
  blank by default, and every payment scenario skips without one.
- The mandate carries no start time; `Receipt.approvedAt` is the approval. The
  earlier proposal's contract notes say periods count from `start`, the first batch
  including any `once` parts is reserved at approval, and a payee stop may be
  backdated — the last of which is not in the vendored schema.

## Goals / Non-Goals

**Goals:** the kit can derive, verify, start, stop, correct, and prove a per-period
transaction, and the pipeline can drive one to exhaustion.

**Non-Goals:** any storefront or buyer behaviour; the listing terms; live
qualification, which stays with the payments service's own tests; a contract change
to the service, which is recorded as unowned work outside this repository.

## Decisions

### D1. Per-period billing is an option param, and the mandate follows it

`PaymentsOptionParams` gains `period` and `reserve_ahead` (ISO durations, fixed
units as `window` is) and an optional `minimum_charge` (an amount in the option's
asset, or a count of periods). An option stating `period` and `reserve_ahead` derives
one `rate` part — `amount` the per-period charge, `period`, `reserveAhead`, `hold:
{until: stop}` — and, where `minimum_charge` is stated, one `once` part for it with
`hold: {for: window}` beside it; an option stating neither derives one `once` part
exactly as today; stating `period` without `reserve_ahead` or the reverse is a
publication blocker. `MandatePolicy` stops requiring a duration for a per-period
option. The buyer's `check` re-derives under its own policy as now, so an option the
buyer did not select cannot be billed per period.

The per-period charge is derived from the Agreement's `amount`, which keeps its unit
— the option's hourly rate — as `floor(amount × period_seconds / 3600)` in minor
units, exact integer arithmetic, refused at publication when it floors to zero, and
re-derived identically by the buyer. Both sides therefore agree the charge from the
Agreement alone, which the correction in D5 needs. Worked, at $2.50/h =
2,500,000 `USD/6`: `PT15M` → 625,000; `PT1M` → 41,666; `PT1H` → 2,500,000.

Example option params and derived parts:

```json
{"payee_account": "…", "asset": "USD/6", "window": "P7D", "period": "PT1H", "reserve_ahead": "PT10M", "minimum_charge": {"periods": 1}}
{"kind": "rate", "asset": "USD/6", "amount": "2500000", "period": "PT1H", "reserveAhead": "PT10M", "hold": {"until": "stop"}}
{"kind": "once", "asset": "USD/6", "amount": "2500000", "hold": {"for": "P7D"}}
```

The `once` part is the enforceable minimum cost of a lease: debited at approval,
reversible only by the payee and the dispute authority, so a buyer cannot recover it
by stopping. The seller reverses it on the undelivered path when the seller failed
to deliver (`converge-ongoing-compute-leases`).

*Rejected:* a separate per-period mechanism ID. *Rejected:* `amount` as the
per-period charge, and `PT1H` only (`negotiate-open-ended-compute-terms` D2).

### D2. Stop authorities are the same for on-demand and spot

`stop` stays `[payer, payee]` whatever the interruption policy. The payee's stop is
the honest way to end billing when the seller must (a withdrawn resource, a lease's
end), and removing it from an on-demand mandate would remove only that. "Won't
preempt" is a promise in the Agreement's `interruption_policy`, remedied through
`reverse` and dispute. A buyer who wants `stop: [payer]` written into the mandate may
ask for it as an option param in a later change; nothing here precludes it.

### D3. `reserve_ahead` must cover polling plus teardown

The reserved horizon is the only funds a seller can rely on between an exhaustion
and noticing it, so the kit refuses to publish an option whose `reserve_ahead` is
shorter than a floor the composing storefront passes it, and the floor is each
storefront's, derived from its real provisioning and teardown latency plus polling,
transport, and clock tolerance — never from the mock profile
(`converge-ongoing-compute-leases`).

### D4. A snapshot is evidence only once verified, bound, and ordered

One `verify_snapshot` beside `verify_receipt`, applied before any reader interprets a
snapshot, checks in order:

1. the proof against the pinned service identity over the snapshot's canonical
   frame, and `livemode` against the expectation;
2. the snapshot's `transaction` against the expected transaction ID, and its
   embedded receipt's deal hash and parties against the persisted mandate and
   Agreement, as `verify_receipt` does for a bare receipt;
3. the part structure against the mandate's parts — a `rate` part where one was
   derived, a `once` part where one was, nothing extra;
4. `observedAt` within a configured tolerance of local time, generous (minutes),
   since its job is to catch a replayed day-old snapshot rather than adjudicate
   skew;
5. `latestEventSequence` against a high-water mark the caller persists per deal,
   refusing a regression.

Every reader of `fundedThrough`, `stop`, `parts`, or `events` goes through it;
`_fully_reversed` moves onto it. An absent `fundedThrough` is "unknown" and
distinct from one in the past. The vendored vectors gain a snapshot vector, the
fixtures a snapshot signer, and the companion's "Snapshot proofs are not evidence"
paragraph is replaced. The frame is confirmed against the service's published
vectors in this change's design session; if the service publishes none, that is a
blocker named in the index.

A receipt embedded in a snapshot whose proof verifies is trusted by that proof: its
fields are checked against the mandate and its own signature need not verify under
the current pin. This is what lets a running deal re-anchor across a service-identity
rotation (D7).

*Rejected:* freshness from the fetch alone — the stored snapshot a restart recovers
from is exactly the replayed one. *Rejected:* trusting only the event stream and
renewing to a fixed lead — it gives up `fundedThrough` as the renewal input.

### D5. `start`, `stop`, and a partial `reverse`, keyed by the caller's decision

`start(transaction, decision)`, `stop(transaction, decision)`, and
`reverse(transaction, decision, part=, amount=)` post `EventCommand{kind, part?,
amount?}` with idempotency keys `{kind}-{decision}`, where the decision is the
caller's durable stop decision or delivery authorization
(`buyer-initiated-compute-termination` D4): a future-effective seller stop, an
earlier buyer cancel, and a later override are different decisions and must not
share a key. The existing whole-transaction `reverse` keeps its `reverse-{txid}` key
for refunds. A `transaction_events(transaction)` read returns the verified snapshot's
events so a caller checks what it already sent.

**The effective time of a stop is corrected inside the contract.** `EventCommand`
carries no effective time, so a stop takes effect at receipt. A rate part's charges
stay held until its stop, and `reverse` accepts `part` and `amount`; so a caller that
learns of a lease's end late reverses, on the rate part, the periods earned after the
effective end — computed from the verified snapshot's `periodsEarned` and the
per-period charge of D1 — and then stops. The buyer is charged nothing after the end
and the payee collects nothing after it. The guarantee the kit offers is stated as:
*charges after a deal's effective end are reversed before they are collected.* A
future-effective stop needs no service support: the caller durably schedules it and
issues an immediate `stop` at the instant; if it is late, it is corrected the same
way.

One confirmation is owed to the service's vectors in design, and is the gate on this
decision: that a partial `reverse{part, amount}` on a running rate part is accepted
before its stop, drawing on the held periods, rather than refused as
`hold_not_reversible` or `insufficient_held_funds`. A second question decides the
caller's crash ordering: whether a `reverse` is still accepted after the stop while
the funds are held. If not, the caller records the reversal as done before it issues
the stop. A payee stop carrying its own effective time, which would make the reversal
the fallback, is recorded as unowned work outside this repository in `ROADMAP.md`.

*Rejected:* assuming payee backdating — not in the vendored schema. *Rejected:*
narrowing the guarantee to "billing ends when the stop is received" — it makes the
buyer bear the seller's outage and turns the buyer's protection into a dispute.
*Rejected:* carrying an effective time in `payload`, which the service never
interprets.

### D6. The period clock runs from the `start` event

The mandate has no start time; approval reserves the first batch; the first period
begins at the `start` event, which either authority may issue. This is what lets a
storefront begin billing at verified delivery and not at approval, and what the
reconciliation of an approved-but-undelivered deal relies on: no period started, so a
`stop` and `reverse` return the reserved batch, the minimum charge excepted at the
seller's discretion. The service refuses `start` on a stopped transaction
(`transaction_stopped`), which the caller's delivery gate treats as the final check.
Confirmed against the service's conformance vectors in design; the double implements
the same.

### D7. Identity rotation re-anchors running deals rather than draining them

The configuration may list a retiring service identity beside the current one with
its retirement date, the shape `service-identity-signing` uses for marketplace
principals. During the overlap a stored receipt signed by the retiring key still
re-verifies and a fresh snapshot signed by the new key verifies. A running deal
re-anchors on the first snapshot it verifies under the new key: that snapshot,
stored as the deal's evidence of approval in place of the bare receipt, vouches for
the embedded receipt (D4), and the deal needs the retiring key for nothing after
that. System status reports deals not yet re-anchored; when none remain the
retiring identity is removed, and only stragglers are drained. `livemode` cannot be
re-anchored — a test-mode deal cannot become a live one — so a mode change stays the
drain the runbook describes. Seller credentials need no design: they are read at
each call, and an unavailable one is a transient the caller treats as "cannot
verify".

*Rejected:* pinning the accepting identity per deal, which trusts a revoked key for
as long as the deal runs.

### D8. Platform credits are `USD/6`

Examples, README, and fixtures move to `USD/6`. No production code names an asset;
the mandate's asset is the Agreement's.

### D9. The fake becomes an in-lane HTTP double, with hostile fixtures

`FakePaymentsClient` grows into an HTTP service the lane stacks can run, built on the
kit's models and signers, with a development signing key that is a well-known fixture
value and says so, trusted by no production configuration: approve, `GET
/transactions/{id}` with a verifiable proof and `fundedThrough`, `stop`, and the
event sequence, `start`, `stop`, partial and whole `reverse`, attachments, and test
controls that exhaust a payer's funds at a chosen instant, serve a stale or
wrong-transaction snapshot, regress a sequence, and rotate the signing identity.
`e2e-tests`' `[payments]` target points at it under the lane profiles, so the
payment scenarios run in the pipeline and stop skipping. It proves the marketplace's
use of the contract; live qualification stays the payments service's.

*Rejected:* keeping payment evidence as owner-run live qualification only. Exhaustion
and hostile snapshots cannot be produced against the live service.

### D10. The composition declares per-period servicing

The registration gains a capability, declared by the composition, that it runs the
per-period continuation; `negotiate-open-ended-compute-terms` D9 publishes per-period
options only where it is declared.

## Open questions

- Confirmations against the service's published vectors, each a blocker if
  unpublished: the snapshot proof's frame (D4); partial reverse of a running rate
  part before its stop, and after it (D5); the period clock from `start` and
  `start` refused on a stopped transaction (D6); a mandate mixing `once` and `rate`
  parts (D1); whether `latestEventSequence` is guaranteed strictly monotonic — if it
  is, D4's timestamp check is redundant.
- Whether the double lives under `kit/arkhai-payments/fixtures`, as the fake does, or
  as a tooling project the lanes build; settled in design against
  `BUILD_AND_PACKAGING.md`'s image rules.
- The option-param shape (D1) is frozen in this change's design session before
  `negotiate-open-ended-compute-terms`' runs.

## Implementation cadence (recommended)

Two rounds. Round 1: the kit — option params, rate-part and minimum derivation,
snapshot verification with vector and fixture, `start`/`stop`/partial `reverse` and
the events read, the servicing capability, `USD/6`. Round 2: the double with its
hostile controls and the lane wiring, with the existing bare-metal and credits
payment scenarios running against it. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2, D5, D6 | `openspec/specs/settlement-servicing/spec.md` |
| D3, D10 | `openspec/specs/settlement-configuration/spec.md` |
| D4 | `settlement-servicing` architecture companion (replacing its snapshot paragraph) and spec |
| D7 | `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" |
| D8 | kit README; `DEPLOYMENT_AND_CONFIG.md` |
| D9 | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`, "Payment Receipts in Tests" |
