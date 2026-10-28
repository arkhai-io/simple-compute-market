# Design

The decisions below were settled with the owner in the goal-level design of
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
on 2026-10-28, across the goal's five changes. This change's own design session
verifies them against the code and the service's vectors and adds the spec deltas;
it does not reopen them without a finding.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `kit/arkhai-payments/src/market_arkhai_payments/models.py`, generated from the
  vendored schema, already has `RatePart{kind, asset, amount, period, reserveAhead,
  hold}`, `Hold = HoldFor | HoldUntilStop`, `RateReservation`, `RateProgress`,
  `PartSnapshot.rate`, `TransactionSnapshot{fundedThrough, stop, events,
  latestEventSequence, livemode}`, `TransactionStop{effectiveAt, cause, sequence,
  settled}` with `Cause ∈ payer | payee | authority | terms`, `TermsStopEvent`,
  `StoredEvent.sequence`, `LifecycleKind ∈ start | stop | reverse`, `Authorities{start,
  stop, reverse}`, `EventCommand{kind, part?, amount?, payload?}`, and
  `SignedTransactionSnapshot{snapshot, proof}`. Nothing outside `models.py` reads any
  of `RatePart`, `fundedThrough`, `TransactionStop`, `latestEventSequence`, or
  `reserveAhead`. There is no transaction-level status; a stopped transaction is one
  whose `snapshot.stop` is present. `EventCommand` has no effective-time field.
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
  reader of snapshot part state, and it is unverified.
- `client.py`: `approve`, `get_transaction`, `poll` (until the transaction exists),
  `attach_agreement`, `ensure_agreement_attached`, `reverse` (idempotency key
  `reverse-{txid}`). No `start`, `stop`, event read, or health call.
- `fixtures/payments_client.py`: `FakePaymentsClient` uses a placeholder proof,
  emits parts `held` or `reversed`, empty events, no `fundedThrough` or `stop`, and
  has no `stop`. `test-vectors/payments.json` has mandates (three `once`, one `rate`
  that is only hash-checked), a receipt, attachments, approvals; no snapshot and no
  lifecycle event. `e2e-tests/settings.toml`'s `[payments]` target is blank by
  default, and every payment scenario skips without one.
- The mandate carries no start time; `Receipt.approvedAt` is the approval. The
  earlier proposal's contract notes say periods count from `start` and the first
  batch is reserved at approval.

## Goals / Non-Goals

**Goals:** the kit can derive, verify, start, stop, and prove a per-period
transaction, and the pipeline can drive one to exhaustion.

**Non-Goals:** any storefront or buyer behaviour; the listing terms; live
qualification, which stays with the payments service's own tests.

## Decisions

### D1. Per-period billing is an option param, and the mandate follows it

`PaymentsOptionParams` gains `period` and `reserve_ahead` (ISO durations, fixed
units as `window` is). An option stating both derives one `rate` part —
`amount` the Agreement's negotiated per-period rate, `period`, `reserveAhead`,
`hold: {until: stop}` — and an option stating neither derives one `once` part exactly
as today; stating one without the other is a publication blocker. `MandatePolicy`
stops requiring a duration for a per-period option. The buyer's `check` re-derives
under its own policy as now, so an option the buyer did not select cannot be billed
per period.

Example option params and derived part:

```json
{"payee_account": "…", "asset": "USD/6", "window": "P7D", "period": "PT1H", "reserve_ahead": "PT10M"}
{"kind": "rate", "asset": "USD/6", "amount": "250000", "period": "PT1H", "reserveAhead": "PT10M", "hold": {"until": "stop"}}
```

*Rejected:* a separate per-period mechanism ID. The mechanism is the same service,
credential, receipt identity, and readiness; only the part differs.

### D2. Stop authorities are the same for on-demand and spot

`stop` stays `[payer, payee]` whatever the interruption policy. The payee's stop is
the honest way to end billing when the seller must (a withdrawn resource, a lease's
end), and removing it from an on-demand mandate would remove only that. "Won't
preempt" is a promise in the Agreement's `interruption_policy`, remedied through
`reverse` and dispute. A buyer who wants it written into the mandate may ask for
`stop: [payer]` as an option param in a later change; nothing here precludes it.

### D3. `reserve_ahead` must cover polling plus teardown

The reserved horizon is the only funds a seller can rely on between an exhaustion
and noticing it, so the option's `reserve_ahead` is declared by the seller as at
least the domain's teardown time plus the continuation's polling cadence, and the
kit refuses to publish an option whose `reserve_ahead` is shorter than a floor the
composing storefront passes it. The floor itself is each storefront's
(`converge-ongoing-compute-leases`).

### D4. Snapshot proofs are verified before snapshot state is evidence

A `verify_snapshot` beside `verify_receipt` checks `SignedTransactionSnapshot.proof`
against the pinned service identity over the snapshot's canonical frame, and
`livemode` against the expectation, and every reader of `fundedThrough`, `stop`,
`parts`, or `events` goes through it; `_fully_reversed` moves onto it. The vendored
vectors gain a snapshot vector, the fixtures a snapshot signer, and the companion's
"Snapshot proofs are not evidence" paragraph is replaced. The frame is confirmed
against the service's published vectors in this change's design session; if the
service publishes none, that is a blocker named in the index, not a frame invented
here.

### D5. `start` and `stop` are client calls with stable idempotency keys

`start(transaction)` and `stop(transaction)` post `EventCommand{kind}` with keys
`start-{txid}` and `stop-{txid}`, as `reverse` does. Because `EventCommand` carries
no effective time, a payee stop's effective time is the service's receipt time; a
storefront that learns of an end late therefore records the site-reported effective
time in its own stop intent and relies on the contract's backdating of payee stops
only where the service exposes it — confirmed against the vectors in design, and if
absent, recorded as a payments-service dependency rather than worked around. A
`transaction_events(transaction)` read returns the snapshot's events so a caller
checks what it already sent.

### D6. The period clock runs from the `start` event

The mandate has no start time; approval reserves the first batch; the first period
begins at the `start` event, which either authority may issue. This is what lets a
storefront begin billing at verified delivery and not at approval, and what the
reconciliation of an approved-but-undelivered deal relies on: no period started, so a
`stop` and `reverse` return the reserved batch. Confirmed against the service's
conformance vectors in design; the double implements the same.

### D7. Platform credits are `USD/6`

Examples, README, and fixtures move to `USD/6`. No production code names an asset;
the mandate's asset is the Agreement's.

### D8. The fake becomes an in-lane HTTP double

`FakePaymentsClient` grows into an HTTP service the three lane stacks can run, built
on the kit's models and receipt signer, with a development signing key that is a
well-known fixture value and says so: approve, `GET /transactions/{id}` with a
verifiable proof and `fundedThrough`, `stop`, and the event sequence, `start`,
`stop`, `reverse`, attachments, and one test control that exhausts a payer's funds
at a chosen instant. `e2e-tests`' `[payments]` target points at it under the lane
profiles, so the payment scenarios run in the pipeline and stop skipping. It proves
the marketplace's use of the contract; live qualification stays the payments
service's, as `ROADMAP.md`'s "Payment qualification boundaries" says.

*Rejected:* keeping payment evidence as owner-run live qualification only, as
`qualify-bare-metal-payment-deal` did. Exhaustion cannot be forced against the live
service, and the goal's correctness claims are about exhaustion and stops.

## Open questions

- The snapshot proof's frame (D4) and whether payee stops can carry an effective time
  (D5): both settled against the service's published vectors in design; each is a
  blocker if the service does not publish them.
- Whether the double lives under `kit/arkhai-payments/fixtures`, as the fake does, or
  as a tooling project the lanes build; settled in design against
  `BUILD_AND_PACKAGING.md`'s image rules.

## Implementation cadence (recommended)

Two rounds. Round 1: the kit — option params, rate-part derivation, snapshot
verification with vector and fixture, `start`/`stop`/events, `USD/6`. Round 2: the
double and the lane wiring, with the existing bare-metal and credits payment
scenarios running against it. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2, D6 | `openspec/specs/settlement-servicing/spec.md` |
| D3 | `openspec/specs/settlement-configuration/spec.md` |
| D4 | `settlement-servicing` architecture companion (replacing its snapshot paragraph) and spec |
| D5 | `settlement-servicing` spec |
| D7 | kit README; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration" |
| D8 | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`, "Payment Receipts in Tests" |
