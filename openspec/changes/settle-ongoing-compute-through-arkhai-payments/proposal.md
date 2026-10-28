## Why

Arkhai payments' first product is compute paid per period from a prepaid balance,
funded by fiat through the payments service: the mandate carries a `rate` part with
`until: stop`, the service reserves funds one quantum ahead per part, and the
transaction stops when a part cannot reserve its next quantum, or when the buyer or the
seller stops it, settling usage to the stop's effective time. The vendored wire
contract (`kit/arkhai-payments/schema/payments.schema.json`, refreshed by
`fix-refresh-payments-contract`) already carries all of it — `RatePart{period,
reserveAhead, hold}`, `HoldUntilStop`, `TransactionSnapshot.fundedThrough`,
`TransactionStop{effectiveAt, cause, sequence, settled}`, event sequence numbers, and
`start`/`stop`/`reverse` lifecycle events — and nothing in this repository uses any of
it: `derive_mandate` builds exactly one `once` part, `PaymentsClient` has no `start` or
`stop` call, only the embedded receipt is verified and a snapshot's own proof is
documented as not evidence (`openspec/specs/settlement-servicing/architecture.md`,
"Snapshot proofs are not evidence"), the kit's `FakePaymentsClient` emits no
`fundedThrough` or stop, and the vendored vectors cover no lifecycle event.

This is the kit half of the roadmap goal that sells compute by the period until either
party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)).
Renamed from `spot-deals-through-arkhai-payments` on 2026-10-28: that proposal was
VM-only and spot-only and called `interruptible` an offering mode, which it is not — it
is an Alkahest release model and a listing flag. The payments mechanics are the same for
on-demand and spot, in both compute domains, and this change owns them; what differs
between the classes is settled in
[`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/).

## What Changes

In `kit/arkhai-payments`, and nowhere domain-specific:

- `PaymentsOptionParams` gains `period` and `reserve_ahead`, both ISO durations. An
  option stating them is billed per period; `derive_mandate` derives one `rate` part
  for it — `amount` the per-period rate from the Agreement, `period` and `reserveAhead`
  from the params, `hold: {until: stop}` — and keeps deriving one `once` part for an
  option without them. `reserve_ahead` is published as a clause field beside `window`,
  so a buyer can bound it.
- The mandate's stop authorities stay `[payer, payee]` for both classes: the payee's
  stop is the honest way to end billing when the seller must, and a routine on-demand
  preemption is a breach remedied through `reverse` and dispute, not by removing the
  authority. `reverse` stays `[payee, dispute authority]`.
- Platform credits are `USD/6`; the kit's examples, README, and fixtures move from
  `USD/2`. No production code names an asset.
- Snapshot-proof verification: `SignedTransactionSnapshot.proof` is verified against
  the pinned service identity before `fundedThrough`, `stop`, parts, or events are read
  as evidence, with a snapshot vector and a receipt-kit fixture, as the archived design
  of `settle-through-arkhai-payments` required of the first reader of snapshot state.
- `start` and `stop` client calls beside `reverse`, each with a stable
  transaction-scoped idempotency key, and a read of the transaction's events so a
  caller checks what was already sent before sending.
- Confirmation against the service's conformance vectors that the period clock runs
  from the `start` event — the mandate has no start time, and approval only reserves
  the first batch — since that is what lets billing begin at delivery.
- The kit's fake grows into an in-lane HTTP double of the payments service: it serves
  approve, snapshots with verifiable proofs carrying `fundedThrough`, `stop`, and the
  event sequence, `start`, `stop`, `reverse`, and a test control that exhausts a
  payer's funds, so every payment scenario runs in the pipeline instead of skipping,
  and exhaustion can be asserted deterministically. It is a test asset of the
  mechanism, never a stand-in for live qualification.

## Payments contract this builds on

Unchanged from the earlier proposal, now vendored: `fundedThrough` per transaction in
the signed snapshot, the earliest current reservation across rate parts; `reserveAhead`
a required per-part term the option declares; a stop with an effective time, a cause
(`payer`, `payee`, `authority`, `terms`), and settled amounts, payee stops backdatable
and never future-dated, any stop ending the whole transaction; per-transaction event
sequence numbers; billing per started period, counted from `start`; the first batch,
including any `once` parts, reserved at approval.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (mandate derivation, snapshot verification, the
lifecycle calls), `settlement-configuration` (the option params and clause fields),
`test-compatibility` (the in-lane double). `.openspec.yaml` sets `skip_specs` until
design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Anything a storefront does with a verified snapshot — renewing a lease, terminating
  on a stop, issuing `start` at delivery, issuing the payee stop at a lease's end:
  [`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/).
- The listing terms that make a deal per-period or preemptible:
  `negotiate-open-ended-compute-terms`.
- Metered quantities other than time; reserved or fixed-interval deals on rate parts;
  push delivery of stop events (the `transaction-webhooks` idea can replace polling
  later without changing this contract).
- Postpaid monthly invoicing, which is outside the goal.

## Dependencies and Related Changes

- Depends on nothing in this repository. The payments service's `rate-parts` contract
  it once waited on is vendored.
- `route-settlement-by-mechanism` (archived 2026-10-09) placed the payment seller
  stage each domain's continuation extends.
- `fix-refresh-payments-contract` (archived 2026-10-21) vendored the contract and left
  rate-part derivation here.

## Compatibility

No backwards-compatibility promise. A per-period option is a new option shape with a
new option ID; existing prepaid options and mandates are unchanged.

## Impact

`kit/arkhai-payments` (mandates, client, receipts, fixtures, vectors, README,
examples), the e2e lane stacks that gain the double, and `e2e-tests`' payment
settings. No domain code.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-servicing`,
  `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A per-period option derives a `rate` part with `until: stop`; a prepaid one a
  `once` part; the Agreement's `amount` is the per-period rate for the former —
  `settlement-servicing` spec.
- Snapshot proofs are verified before snapshot state is evidence, replacing the
  companion's "Snapshot proofs are not evidence" paragraph — `settlement-servicing`
  architecture companion.
- The period clock runs from the `start` event, so billing begins when the payee
  declares delivery — `settlement-servicing` spec.
- The in-lane payments double, what it proves and what it does not —
  `test-compatibility` spec and `docs/development/TESTING.md`, "Payment Receipts in
  Tests".
